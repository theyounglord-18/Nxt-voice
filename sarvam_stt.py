"""
Custom Sarvam AI STT (Speech-to-Text) integration for LiveKit Agents
Using official sarvamai SDK with saaras:v1 model for native Telugu support
"""
from sarvamai import SarvamAI
from typing import Optional
from livekit.agents import stt, utils, APIConnectOptions
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS
import logging
import base64
import asyncio

logger = logging.getLogger("sarvam-stt")


class SarvamSTT(stt.STT):
    """Sarvam AI Speech-to-Text implementation for LiveKit using official SDK"""
    
    def __init__(
        self,
        api_key: str,
        language_code: str = "te-IN",  # Telugu by default
        model: str = "saarika:v2.5",  # Latest Sarvam STT model (fixed typo!)
        sample_rate: int = 16000,  # Standard for telephony
    ):
        # Initialize parent STT class
        super().__init__(
            capabilities=stt.STTCapabilities(streaming=False, interim_results=False)
        )
        self.client = SarvamAI(api_subscription_key=api_key)
        self.language_code = language_code
        self.sarvam_model = model
        self._sample_rate = sample_rate
        
        logger.info(
            f"🎙️ Sarvam STT initialized: language={language_code}, "
            f"model={model}, sample_rate={sample_rate}"
        )
    
    async def _recognize_impl(
        self,
        buffer: utils.AudioBuffer,
        *,
        language: Optional[str] = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> stt.SpeechEvent:
        """Internal implementation required by STT base class - must return SpeechEvent"""
        try:
            # Convert audio buffer to WAV format
            import wave
            import io
            import numpy as np
            from livekit import rtc
            
            # Combine all audio frames into one
            frame = rtc.combine_audio_frames(buffer)
            
            # Create WAV file in memory
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav_file:
                wav_file.setnchannels(frame.num_channels)
                wav_file.setsampwidth(2)  # 16-bit audio
                wav_file.setframerate(frame.sample_rate)
                
                # Convert float32 audio to int16 (safely handle NaN and inf values)
                audio_data = np.frombuffer(frame.data, dtype=np.float32)
                # Replace NaN and inf with 0
                audio_data = np.nan_to_num(audio_data, nan=0.0, posinf=1.0, neginf=-1.0)
                # Clip to [-1.0, 1.0] range to prevent overflow
                audio_data = np.clip(audio_data, -1.0, 1.0)
                # Convert to int16
                audio_int16 = (audio_data * 32767).astype(np.int16)
                
                wav_file.writeframes(audio_int16.tobytes())
            
            # Get WAV data as bytes (not base64)
            wav_buffer.seek(0)
            wav_bytes = wav_buffer.read()
            
            # Debug: Check audio characteristics
            audio_duration = len(audio_data) / frame.sample_rate
            audio_rms = np.sqrt(np.mean(audio_data**2))  # Root Mean Square (volume level)
            audio_max = np.max(np.abs(audio_data))
            
            logger.info(f"🔊 Recognizing {len(wav_bytes)} bytes of audio with Sarvam STT (language={language or self.language_code})")
            logger.info(f"🎚️ Audio Stats: duration={audio_duration:.2f}s, RMS={audio_rms:.4f}, max={audio_max:.4f}, contains_speech={audio_rms > 0.01}")
            
            # Skip STT if audio appears to be silence (RMS too low)
            if audio_rms < 0.01:
                logger.warning(f"🔇 Audio RMS too low ({audio_rms:.4f} < 0.01) - likely silence or noise, skipping STT")
                return stt.SpeechEvent(
                    type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                    alternatives=[
                        stt.SpeechData(
                            language=language or self.language_code,
                            text="",
                        )
                    ],
                )
            
            # Call Sarvam API synchronously in executor to avoid blocking
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.speech_to_text.transcribe(
                    file=wav_bytes,  # Correct parameter name!
                    language_code=language or self.language_code,
                    model=self.sarvam_model,  # Use the initialized model name
                )
            )
            
            # Debug: Log the full response
            logger.info(f"📥 Sarvam API Response: {response}")
            logger.info(f"📥 Response type: {type(response)}, attributes: {dir(response)}")
            
            # Extract transcript from response - try multiple attributes
            transcript = ""
            if hasattr(response, 'transcript'):
                transcript = response.transcript
            elif hasattr(response, 'text'):
                transcript = response.text
            elif hasattr(response, 'transcription'):
                transcript = response.transcription
            else:
                # If it's a dict or has dict-like access
                try:
                    if isinstance(response, dict):
                        transcript = response.get('transcript', '') or response.get('text', '')
                    else:
                        transcript = str(response)
                except Exception:  # Fixed linting error
                    transcript = ""
            
            if transcript:
                logger.info(f"✅ Sarvam STT transcription: '{transcript}'")
            else:
                logger.warning(f"⚠️ No transcript returned from Sarvam STT. Response: {response}")
            
            # Return SpeechEvent as required
            return stt.SpeechEvent(
                type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                alternatives=[
                    stt.SpeechData(
                        language=language or self.language_code,
                        text=transcript,
                    )
                ],
            )
            
        except Exception as e:
            logger.error(f"❌ Error in Sarvam STT recognition: {e}", exc_info=True)
            # Return empty transcript on error
            return stt.SpeechEvent(
                type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                alternatives=[
                    stt.SpeechData(
                        language=language or self.language_code,
                        text="",
                    )
                ],
            )
