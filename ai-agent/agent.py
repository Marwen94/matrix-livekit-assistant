"""
AI Agent for LiveKit
Handles STT, LLM (Ollama), and TTS (Kokoro) in a group call.
"""

import os
import json
import asyncio
import logging
import httpx
import websockets
import numpy as np
import soundfile as sf
import resampy
from typing import List, Optional

from livekit import agents, rtc
from livekit.agents import cli
from livekit.plugins import silero

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-agent")

# Configuration
LIVEKIT_URL = os.environ.get("LIVEKIT_URL")
LIVEKIT_API_KEY = os.environ.get("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.environ.get("LIVEKIT_API_SECRET")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
STT_WS_URL = os.environ.get("STT_WS_URL", "ws://stt-service:8000/ws/transcribe")
TTS_URL = os.environ.get("TTS_URL", "http://tts-service:8880/v1/audio/speech")
TTS_VOICE = os.environ.get("TTS_VOICE", "af_heart")
ASSISTANT_USER_ID = os.environ.get("ASSISTANT_USER_ID")
LOG_TRANSCRIPTS = os.environ.get("LOG_TRANSCRIPTS", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
LLM_SYSTEM_PROMPT = os.environ.get(
    "LLM_SYSTEM_PROMPT",
    "You are a helpful AI assistant in a group voice call. Keep answers concise - 2 to 3 sentences maximum. Avoid markdown, bullet points, and special characters since your response will be spoken aloud.",
)

class CallAssistant:
    def __init__(self, room: rtc.Room):
        self.room = room
        self.history: List[dict] = [
            {"role": "system", "content": LLM_SYSTEM_PROMPT}
        ]
        self.history_lock = asyncio.Lock()
        self.audio_out_queue = asyncio.Queue()
        self.transcript_queue = asyncio.Queue()
        self.stt_ws: Optional[websockets.WebSocketClientProtocol] = None
        self.audio_track: Optional[rtc.LocalAudioTrack] = None
        
    async def start(self):
        """Starts the assistant's tasks."""
        # Create and publish audio track
        source = rtc.AudioSource(48000, 1)
        self.audio_track = rtc.LocalAudioTrack.create_audio_track("assistant-voice", source)
        options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        await self.room.local_participant.publish_track(self.audio_track, options)
        
        # Start concurrent tasks
        asyncio.create_task(self.stt_handler())
        asyncio.create_task(self.llm_tts_pipeline())
        asyncio.create_task(self.playback_handler(source))
        
        # Subscribe to all existing tracks
        for remote_participant in self.room.remote_participants.values():
            for track_publication in remote_participant.track_publications.values():
                if track_publication.kind == rtc.TrackKind.KIND_AUDIO:
                    track_publication.set_subscribed(True)

    async def connect_stt(self):
        """Connects to the STT service WebSocket."""
        if not self.stt_ws or self.stt_ws.closed:
            self.stt_ws = await websockets.connect(STT_WS_URL)
            logger.info("Connected to STT service")

    async def stt_handler(self):
        """Receives transcripts from STT service."""
        await self.connect_stt()
        try:
            async for message in self.stt_ws:
                data = json.loads(message)
                if data.get("type") == "final":
                    text = data.get("text", "").strip()
                    if text:
                        if LOG_TRANSCRIPTS:
                            logger.info("STT Final: %s", text)
                        await self.transcript_queue.put(text)
        except Exception as e:
            logger.error(f"STT Handler error: {e}")

    async def llm_tts_pipeline(self):
        """Handles LLM generation and TTS conversion."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            while True:
                user_text = await self.transcript_queue.get()
                
                async with self.history_lock:
                    self.history.append({"role": "user", "content": user_text})
                    # Cap history
                    if len(self.history) > 21: # system + 20 turns
                        self.history = [self.history[0]] + self.history[-20:]
                    
                    messages = list(self.history)

                try:
                    # 1. LLM Chat (Ollama)
                    response_text = ""
                    current_sentence = ""
                    
                    async with client.stream(
                        "POST", 
                        f"{OLLAMA_URL}/api/chat",
                        json={"model": OLLAMA_MODEL, "messages": messages, "stream": True}
                    ) as resp:
                        async for line in resp.aiter_lines():
                            if not line: continue
                            chunk = json.loads(line)
                            if "message" in chunk:
                                content = chunk["message"]["content"]
                                response_text += content
                                current_sentence += content
                                
                                # Split on sentence boundaries
                                if any(punct in content for punct in [".", "!", "?"]):
                                    sentence_to_speak = current_sentence.strip()
                                    if sentence_to_speak:
                                        asyncio.create_task(self.process_tts(client, sentence_to_speak))
                                    current_sentence = ""
                    
                    if current_sentence.strip():
                        asyncio.create_task(self.process_tts(client, current_sentence.strip()))
                    
                    async with self.history_lock:
                        self.history.append({"role": "assistant", "content": response_text})
                        
                except Exception as e:
                    logger.error(f"LLM/TTS Pipeline error: {e}")

    async def process_tts(self, client: httpx.AsyncClient, text: str):
        """Sends text to TTS and puts resulting audio in the playback queue."""
        try:
            resp = await client.post(
                TTS_URL,
                json={
                    "model": "kokoro",
                    "input": text,
                    "voice": TTS_VOICE,
                    "response_format": "wav"
                }
            )
            if resp.status_code == 200:
                # Load WAV bytes
                import io
                data, samplerate = sf.read(io.BytesIO(resp.content))
                
                # Resample 24k -> 48k
                if samplerate != 48000:
                    data = resampy.resample(data, samplerate, 48000)
                
                # Convert to 16-bit PCM
                pcm_data = (data * 32767).astype(np.int16)
                await self.audio_out_queue.put(pcm_data)
        except Exception as e:
            logger.error(f"TTS error for '{text}': {e}")

    async def playback_handler(self, source: rtc.AudioSource):
        """Plays back audio chunks from the queue back-to-back."""
        while True:
            pcm_data = await self.audio_out_queue.get()
            # LiveKit expects 10ms or 20ms frames. 
            # 48kHz * 0.02s = 960 samples
            frame_size = 960 
            for i in range(0, len(pcm_data), frame_size):
                chunk = pcm_data[i:i + frame_size]
                if len(chunk) < frame_size:
                    # Pad last chunk
                    chunk = np.pad(chunk, (0, frame_size - len(chunk)))
                
                audio_frame = rtc.AudioFrame(
                    data=chunk.tobytes(),
                    sample_rate=48000,
                    num_channels=1,
                    samples_per_channel=frame_size
                )
                await source.capture_frame(audio_frame)
                await asyncio.sleep(0.02) # Match the frame duration

    async def push_audio(self, frame: rtc.AudioFrame):
        """Pushes incoming audio from users to the STT service."""
        await self.connect_stt()
        # Convert to 16kHz mono PCM
        # (Simplified: assumes input is already 16k or handles via resampling if needed)
        # LiveKit frames are usually 48k.
        if frame.sample_rate != 16000:
            # Resample 48k -> 16k
            data = np.frombuffer(frame.data, dtype=np.int16).astype(np.float32) / 32768.0
            resampled = resampy.resample(data, frame.sample_rate, 16000)
            pcm_16k = (resampled * 32767).astype(np.int16).tobytes()
        else:
            pcm_16k = frame.data
            
        await self.stt_ws.send(pcm_16k)

    async def send_silence_sentinel(self):
        """Sends 2s of silence to flush STT."""
        if self.stt_ws and not self.stt_ws.closed:
            silence = np.zeros(16000 * 2, dtype=np.int16).tobytes()
            await self.stt_ws.send(silence)

async def entrypoint(ctx: agents.JobContext):
    logger.info(f"Connecting to room {ctx.room.name}")
    await ctx.connect()
    
    assistant = CallAssistant(ctx.room)
    await assistant.start()
    
    # VAD setup
    vad = silero.VAD()
    
    @ctx.room.on("track_subscribed")
    def on_track_subscribed(track: rtc.Track, publication: rtc.TrackPublication, participant: rtc.RemoteParticipant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            asyncio.create_task(handle_audio_stream(track, assistant, vad))

    async def handle_audio_stream(track: rtc.AudioTrack, assistant: CallAssistant, vad: silero.VAD):
        audio_stream = rtc.AudioStream(track)
        vad_stream = vad.stream()
        
        async def process_vad():
            async for event in vad_stream:
                if event.type == silero.VADEventType.START:
                    logger.info("Speech started")
                    await assistant.connect_stt()
                elif event.type == silero.VADEventType.END:
                    logger.info("Speech ended, sending sentinel")
                    await assistant.send_silence_sentinel()

        asyncio.create_task(process_vad())

        async for frame in audio_stream:
            # We push audio while the vad_stream is active
            # The STT service handles the chunks
            await assistant.push_audio(frame)
            vad_stream.push_frame(frame)

    # Keep alive
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    cli.run_app(agents.WorkerOptions(request_fnc=entrypoint))
