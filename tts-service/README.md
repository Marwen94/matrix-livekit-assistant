# TTS Service (Kokoro-82M ONNX)

This service provides high-quality, fast text-to-speech using the Kokoro-82M model running on ONNX.

## Usage

### Endpoint
`POST http://tts-service:8880/v1/audio/speech`

### Request Body
```json
{
  "model": "kokoro",
  "input": "Hello world",
  "voice": "af_heart",
  "response_format": "wav"
}
```

### Available Voices
- `af_heart` (Default, feminine)
- `am_adam` (Masculine)
- More can be added by mounting them to the container.

## Configuration
- `KOKORO_VOICES`: Comma-separated list of voices to load on startup.

## Performance
- **RTF**: ~0.16 on modern CPUs (6x faster than real-time).
- **Latency**: First-sentence latency is approximately 0.3s - 0.8s.
