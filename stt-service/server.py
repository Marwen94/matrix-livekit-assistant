"""
STT Service
Real-time streaming speech-to-text using faster-whisper and whisper-streaming.
"""

import os
import json
import asyncio
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from whisper_online import FasterWhisperASR, OnlineASRProcessor

app = FastAPI()

# Configuration from environment
STT_MODEL = os.environ.get("STT_MODEL", "large-v3-turbo")
STT_COMPUTE_TYPE = os.environ.get("STT_COMPUTE_TYPE", "int8")
STT_MIN_CHUNK_SIZE = float(os.environ.get("STT_MIN_CHUNK_SIZE", 1.0))
STT_THREADS = int(os.environ.get("STT_THREADS", 4))
CACHE_DIR = "/model-cache"

# Global ASR instance (shared across connections to save memory, 
# but each connection gets its own OnlineASRProcessor)
asr = FasterWhisperASR(
    modelsize=STT_MODEL,
    lan="auto",
    cache_dir=CACHE_DIR,
    compute_type=STT_COMPUTE_TYPE,
    device="cpu",
)

# Set threads
asr.model.inter_threads = STT_THREADS
asr.model.intra_threads = 2

@app.websocket("/ws/transcribe")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    # Initialize processor for this connection
    processor = OnlineASRProcessor(asr, min_chunk_size=STT_MIN_CHUNK_SIZE)
    
    try:
        while True:
            # Receive binary frame (PCM 16-bit 16kHz mono)
            data = await websocket.receive_bytes()
            
            # Convert to float32 numpy array
            audio_chunk = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            
            # Process audio
            processor.insert_audio_chunk(audio_chunk)
            
            # Get transcription
            # The processor emits text based on local agreement policy
            output = processor.process_iter()
            
            if output:
                # whisper-streaming returns (start, end, text) or similar
                # depending on the specific version/implementation.
                # Usually, it's a tuple of (beg, end, text)
                beg, end, text = output
                
                # Check if it's "final" (stable) or partial
                # In whisper-streaming, process_iter returns stable hypotheses
                await websocket.send_json({
                    "type": "final",
                    "text": text.strip()
                })
                
    except WebSocketDisconnect:
        # Flush and close
        processor.finish()
    except Exception as e:
        print(f"Error in STT WebSocket: {e}")
        await websocket.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
