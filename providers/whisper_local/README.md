# PersonalAI: local Whisper transcriber

In-process speech-to-text via [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
(CTranslate2). Implements the `Transcriber` port. The model is downloaded once from Hugging Face
then cached locally and runs offline (CPU; Apple Silicon supported). Multilingual (~99 languages,
auto-detected). Default model: `large-v3-turbo`.
