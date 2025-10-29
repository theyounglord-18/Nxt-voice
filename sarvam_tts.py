"""
Custom Sarvam AI TTS integration for LiveKit Agents
Using official sarvamai SDK
"""
from sarvamai import SarvamAI
from typing import Optional
from livekit.agents import tts, APIConnectOptions, utils
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS
import logging
import base64
import asyncio
import wave
import io

logger = logging.getLogger("sarvam-tts")

class SarvamTTS(tts.TTS):
    """Sarvam AI Text-to-Speech implementation for LiveKit using official SDK"""
    
    def __init__(
        self,
        api_key: str,
        speaker: str = "manisha",  # Telugu female voice (as per your preference)
        target_language_code: str = "te-IN",  # Telugu
        model: str = "bulbul:v2",  # Latest Sarvam TTS model
        pitch: float = 0,  # -10 to 10
        pace: float = 1.0,  # 0.5 to 2.0 (normal speed)
        loudness: float = 1.0,  # 0.5 to 2.0 (normal volume)
        speech_sample_rate: int = 22050,  # 8000, 16000, 22050, 24000
        enable_preprocessing: bool = True,
    ):
        # Initialize parent TTS class with required parameters
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),  # Sarvam doesn't support streaming
            sample_rate=speech_sample_rate,
            num_channels=1,  # Mono audio
        )
        self.client = SarvamAI(api_subscription_key=api_key)
        self.speaker = speaker
        self.target_language_code = target_language_code
        self.sarvam_model = model  # Renamed from 'model' to avoid conflict with parent property
        self.pitch = pitch
        self.pace = pace
        self.loudness = loudness
        self.speech_sample_rate = speech_sample_rate
        self.enable_preprocessing = enable_preprocessing
        
        logger.info(
            f"🎙️ Sarvam TTS initialized: speaker={speaker}, "
            f"language={target_language_code}, model={model}"
        )
        
    def synthesize(
        self, 
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> "SarvamChunkedStream":
        """Synthesize speech from text using Sarvam AI SDK"""
        return SarvamChunkedStream(tts=self, input_text=text, conn_options=conn_options)


class SarvamChunkedStream(tts.ChunkedStream):
    """ChunkedStream implementation for Sarvam TTS"""
    
    def __init__(self, *, tts: SarvamTTS, input_text: str, conn_options: APIConnectOptions):
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._tts: SarvamTTS = tts
        
    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        """Run the TTS synthesis with graceful fallback"""
        
        if not self._input_text or not self._input_text.strip():
            logger.warning("Empty text provided to Sarvam TTS, skipping")
            return
        
        try:
            logger.info(f"🔊 Synthesizing with Sarvam: '{self._input_text[:50]}...'")
            
            # Run synchronous SDK call in executor to avoid blocking
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._tts.client.text_to_speech.convert(
                    text=self._input_text,
                    target_language_code=self._tts.target_language_code,
                    speaker=self._tts.speaker,
                    pitch=self._tts.pitch,
                    pace=self._tts.pace,
                    loudness=self._tts.loudness,
                    speech_sample_rate=self._tts.speech_sample_rate,
                    enable_preprocessing=self._tts.enable_preprocessing,
                    model=self._tts.sarvam_model
                )
            )
            
            # Extract audio from response
            if hasattr(response, 'audios') and response.audios:
                audio_base64 = response.audios[0]
                
                # Decode base64 to audio bytes (WAV format)
                wav_data = base64.b64decode(audio_base64)
                
                logger.info(f"✅ Sarvam TTS generated {len(wav_data)} bytes of WAV audio")
                
                # Verify it's a valid WAV file
                with wave.open(io.BytesIO(wav_data), 'rb') as wav_file:
                    num_channels = wav_file.getnchannels()
                    sample_width = wav_file.getsampwidth()
                    framerate = wav_file.getframerate()
                    
                    logger.info(f"WAV format: {num_channels} channels, {sample_width} bytes/sample, {framerate} Hz")
                
                # Initialize the output emitter BEFORE pushing audio
                # Push the complete WAV file (with headers) so LiveKit can decode it
                output_emitter.initialize(
                    request_id=utils.shortuuid(),
                    sample_rate=self._tts.speech_sample_rate,
                    num_channels=1,
                    mime_type="audio/wav",  # Complete WAV file with headers
                )
                
                # Push the complete WAV data (not just PCM)
                output_emitter.push(wav_data)
                
            else:
                logger.error("No audio returned from Sarvam API")
                raise ValueError("No audio data received from Sarvam TTS")
                    
        except Exception as e:
            logger.error(f"❌ Error synthesizing with Sarvam: {e}", exc_info=True)
            raise
