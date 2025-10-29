# Telugu AI Voice Agent - Success Coach

<p>
  <a href="https://livekit.io/">
    <img src="https://img.shields.io/badge/LiveKit-Agents-blue" alt="LiveKit">
  </a>
  <a href="https://sarvam.ai/">
    <img src="https://img.shields.io/badge/Sarvam-AI-green" alt="Sarvam AI">
  </a>
  <a href="https://ai.google.dev/">
    <img src="https://img.shields.io/badge/Google-Gemini-orange" alt="Google Gemini">
  </a>
</p>

A bilingual (Telugu/English) AI voice agent for educational counseling built with LiveKit Agents Framework. The agent uses **Sarvam AI** for native Telugu speech recognition and synthesis, **Google Gemini** for natural language understanding, and **LiveKit + Twilio** for telephony infrastructure.

## 🌟 Features

- **📞 Outbound & Inbound Calls**: Make and receive phone calls via SIP/PSTN
- **🇮🇳 Native Telugu Support**: Powered by Sarvam AI's STT (`saarika:v2.5`) and TTS (`bulbul:v2`)
- **🌐 Bilingual Conversations**: Automatically detects and switches between Telugu and English
- **🎯 Intelligent Routing**: Function calling for call transfers and voicemail detection
- **🔇 Silence Monitoring**: Automatic conversation flow management with timeout handling
- **📊 Real-time Analytics**: Track conversation topics, user engagement, and call metrics
- **🎙️ Voice Activity Detection**: Silero VAD for accurate speech detection

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Phone Network (PSTN)                   │
│                    (Your Phone Number)                      │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                    Twilio SIP Trunk                         │
│              (SIP Inbound/Outbound Routing)                 │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                    LiveKit Cloud/Server                     │
│              (SIP Room, Audio Routing, WebRTC)              │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                  LiveKit Agent (This App)                   │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  STT: Sarvam AI (saarika:v2.5)                       │  │
│  │       ↓                                               │  │
│  │  LLM: Google Gemini (gemini-1.5-flash-002)           │  │
│  │       ↓                                               │  │
│  │  TTS: Sarvam AI (bulbul:v2)                          │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## 📋 Prerequisites

### Required Accounts & API Keys

1. **LiveKit Cloud Account** (or self-hosted LiveKit server)
   - Sign up at: https://cloud.livekit.io
   - Get: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`

2. **Twilio Account** (for phone calls)
   - Sign up at: https://www.twilio.com
   - Purchase a phone number
   - Configure SIP trunk

3. **Sarvam AI Account** (for Telugu STT/TTS)
   - Sign up at: https://www.sarvam.ai
   - Get: `SARVAM_API_KEY`

4. **Google AI Studio** (for Gemini LLM)
   - Get API key at: https://aistudio.google.com/apikey
   - Get: `GOOGLE_API_KEY`

### System Requirements

- Python 3.11+
- Windows/Linux/macOS
- Internet connection for API calls

## 🚀 Quick Start

### 1. Clone & Install

```bash
# Clone the repository
git clone https://github.com/theyounglord-18/Nxt-voice.git
cd Nxt-voice

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# On Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Create a `.env.local` file in the project root:

```env
# LiveKit Configuration
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxxxxxxxxxxxx
LIVEKIT_API_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Sarvam AI (Telugu STT/TTS)
SARVAM_API_KEY=your-sarvam-api-key

# Google Gemini (LLM)
GOOGLE_API_KEY=your-google-api-key

# SIP Configuration (for outbound calls)
SIP_OUTBOUND_TRUNK_ID=ST_xxxxxxxxxxxxxxxx
```

### 3. Run the Agent

```bash
# Development mode (auto-reload on code changes)
python agent.py dev

# Production mode
python agent.py start
```

## 📞 LiveKit + Twilio Integration Guide

### Step 1: Set Up LiveKit Cloud

1. **Create LiveKit Cloud Account**
   - Go to https://cloud.livekit.io
   - Sign up for a free account
   - Create a new project

2. **Get LiveKit Credentials**
   - Navigate to **Settings** → **Keys**
   - Copy your:
     - `LIVEKIT_URL` (e.g., `wss://your-project.livekit.cloud`)
     - `LIVEKIT_API_KEY` (e.g., `APIxxxxxxxxx`)
     - `LIVEKIT_API_SECRET` (e.g., `xxxxxxxxxxxxxxxx`)

3. **Enable SIP in LiveKit**
   - Go to **Settings** → **SIP**
   - Enable SIP feature (may require upgrading to paid plan)
   - Note: SIP is required for phone call integration

### Step 2: Set Up Twilio

#### 2.1 Create Twilio Account

1. Go to https://www.twilio.com/try-twilio
2. Sign up and verify your account
3. Complete phone number verification

#### 2.2 Purchase a Phone Number

1. Navigate to **Phone Numbers** → **Buy a Number**
2. Search for a number in your desired country/region
3. Filter by "Voice" capabilities
4. Purchase the number (costs ~$1-2/month)
5. Note down your phone number (e.g., `+1234567890`)

#### 2.3 Configure Twilio Elastic SIP Trunk

1. **Create SIP Trunk**
   - Go to **Elastic SIP Trunking** → **Trunks**
   - Click **Create new SIP Trunk**
   - Name it (e.g., "LiveKit Integration")
   - Click **Create**

2. **Add Origination URI** (for inbound calls - LiveKit → Twilio)
   - Go to your SIP Trunk → **Origination**
   - Click **Add new Origination URI**
   - Enter: `sip.livekit.cloud` (or your LiveKit server domain)
   - Priority: `10`
   - Weight: `10`
   - Enabled: ✅
   - Click **Add**

3. **Add Termination URI** (for outbound calls - Twilio → LiveKit)
   - Go to your SIP Trunk → **Termination**
   - Click **Add new Termination SIP URI**
   - Copy the **Termination SIP URI** shown (e.g., `your-trunk.pstn.twilio.com`)
   - Enable **SIP Registration**: ❌ (not needed)
   - Click **Save**

4. **Configure Authentication** (optional but recommended)
   - Go to **Termination** → **Credentials**
   - Add IP Access Control List or SIP Credentials
   - For LiveKit Cloud, add their IP addresses to whitelist

5. **Assign Phone Number to Trunk**
   - Go to **Phone Numbers** → **Manage** → **Active Numbers**
   - Click on your purchased number
   - Under **Voice & Fax**, configure:
     - **Configure with**: `SIP Trunk`
     - **SIP Trunk**: Select your created trunk
   - Click **Save**

### Step 3: Configure LiveKit SIP Integration

#### 3.1 Create SIP Trunk in LiveKit

1. **Via LiveKit Dashboard**
   - Go to **Settings** → **SIP** → **Trunks**
   - Click **Create SIP Trunk**
   - Fill in details:
     - **Name**: `Twilio Trunk`
     - **Outbound Address**: `your-trunk.pstn.twilio.com` (from Twilio)
     - **Outbound Number**: Your Twilio phone number (e.g., `+1234567890`)
     - **Inbound Numbers**: Add numbers you want to receive calls on
     - **Authentication**: Add if configured in Twilio
   - Click **Create**
   - Copy the **Trunk ID** (e.g., `ST_xxxxxxxxxxxxxxxx`)

2. **Via LiveKit CLI** (alternative method)
   ```bash
   # Install LiveKit CLI
   brew install livekit-cli  # macOS
   # or download from https://github.com/livekit/livekit-cli

   # Create SIP Trunk
   lk sip trunk create \
     --name "Twilio Trunk" \
     --outbound-address "your-trunk.pstn.twilio.com" \
     --outbound-number "+1234567890"
   ```

#### 3.2 Configure SIP Dispatch Rules

1. **Create Dispatch Rule for Inbound Calls**
   - In LiveKit Dashboard: **SIP** → **Dispatch Rules**
   - Click **Create Dispatch Rule**
   - Configure:
     - **Trunk**: Select your Twilio trunk
     - **Rule Type**: `Inbound`
     - **Match Pattern**: `.*` (all incoming calls) or specific number pattern
     - **Room Name Template**: `call-{phone}`
     - **Agent Name**: `outbound-caller` (must match your agent)
   - Click **Create**

2. **Verify Outbound Configuration**
   - Your `SIP_OUTBOUND_TRUNK_ID` should be set in `.env.local`
   - This trunk will be used when making outbound calls

### Step 4: Test the Integration

#### Test Inbound Calls

1. **Start your agent**:
   ```bash
   python agent.py dev
   ```

2. **Call your Twilio number** from your phone
   - You should hear the AI agent greet you
   - Have a conversation in Telugu or English

3. **Check logs** for connection status and conversation flow

#### Test Outbound Calls

1. **Create a dispatch to call a number**:
   ```bash
   # Using LiveKit CLI
   lk dispatch create \
     --new-room \
     --agent-name outbound-caller \
     --metadata '{"phone_number": "+919876543210", "transfer_to": "+911234567890"}'
   ```

2. **Or use the LiveKit Dashboard**:
   - Go to **Rooms** → **Create Room**
   - Add metadata:
     ```json
     {
       "phone_number": "+919876543210",
       "transfer_to": "+911234567890"
     }
     ```
   - Dispatch agent: `outbound-caller`

3. **The phone at `+919876543210` should ring**
   - When answered, the AI agent will start speaking

## 🔧 Configuration

### Voice Activity Detection (VAD)

Edit `agent.py` to customize VAD settings:

```python
vad = silero.VAD.load(
    activation_threshold=0.35,  # Lower = more sensitive (0.0-1.0)
    min_speech_duration=0.1,    # Minimum speech duration in seconds
    min_silence_duration=0.5,   # Silence before considering speech ended
    padding_duration=0.1,        # Audio padding around speech
)
```

### Silence Monitoring

```python
# Timing thresholds (in seconds)
USER_SILENCE_THRESHOLD = 5.0      # First check after this silence
SECOND_CHECK_WAIT_TIME = 15.0     # Second check wait time
SILENCE_CHECK_INTERVAL = 1.0      # How often to check for silence
```

### Sarvam AI Settings

```python
stt = SarvamSTT(
    api_key=sarvam_api_key,
    language_code="te-IN",        # Telugu
    model="saarika:v2.5",         # Latest STT model
    sample_rate=16000,            # Phone quality
)

tts = SarvamTTS(
    api_key=sarvam_api_key,
    speaker="abhilash",           # Male Telugu voice
    target_language_code="te-IN", # Telugu output
    model="bulbul:v2",            # Latest TTS model
    pitch=0.95,                   # Natural pitch
    pace=1.05,                    # Slightly faster
    loudness=1.5,                 # Clear volume
    speech_sample_rate=22050,     # High quality
)
```

### Gemini LLM Settings

```python
llm = google.LLM(
    model="gemini-1.5-flash-002",  # Versioned model for v1beta API
    temperature=0.68,              # Creativity level (0.0-1.0)
)
```

## 🔍 Troubleshooting

### Common Issues

#### 1. Gemini API 404 Error
```
models/gemini-1.5-flash is not found for API version v1beta
```
**Solution**: Use versioned model `gemini-1.5-flash-002` instead of `gemini-1.5-flash`

#### 2. Sarvam STT Model Error
```
Input should be 'saarika:v1', 'saarika:v2', 'saarika:v2.5'
```
**Solution**: Use `saarika:v2.5` (not `saaras:v1`)

#### 3. SIP Call Not Connecting
- Verify `SIP_OUTBOUND_TRUNK_ID` matches your LiveKit trunk ID
- Check Twilio trunk configuration (Origination + Termination URIs)
- Ensure phone number is in E.164 format: `+[country code][number]`
- Check LiveKit SIP credits/quota

#### 4. No Audio / Agent Not Speaking
- Verify `SARVAM_API_KEY` is valid
- Check TTS model is set to `bulbul:v2`
- Ensure speaker is set to valid voice (`abhilash`, `meera`, etc.)
- Check network connectivity to Sarvam AI API

#### 5. Agent Disconnects Immediately
- Check silence monitoring thresholds aren't too aggressive
- Verify VAD settings (activation_threshold)
- Look for LLM API errors in logs

### Debug Mode

Enable verbose logging:

```bash
# Set log level to DEBUG
python agent.py dev --log-level DEBUG
```

Check specific components:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Or for specific modules
logging.getLogger("sarvam-stt").setLevel(logging.DEBUG)
logging.getLogger("outbound-caller").setLevel(logging.DEBUG)
```

## 📊 Monitoring & Analytics

The agent logs detailed analytics:

```python
# Tracked metrics
- Conversation topics discussed
- User engagement level
- Call duration
- Silence events
- Tool/function calls
- Hangup reasons
```

Check logs for insights:
- `📢` Proactive greeting
- `🎯` Conversation activity
- `🔴` Silence detected
- `📵` Call ended
- `⚠️` Warnings/errors

## 🔐 Security Best Practices

1. **Never commit API keys** to version control
2. **Use `.env.local`** for sensitive credentials (already in `.gitignore`)
3. **Rotate API keys** regularly
4. **Enable IP whitelisting** on Twilio for LiveKit IPs
5. **Use SIP authentication** between Twilio and LiveKit
6. **Monitor API usage** to detect anomalies

## 📚 Additional Resources

- **LiveKit Docs**: https://docs.livekit.io/agents/
- **Twilio SIP Trunking**: https://www.twilio.com/docs/sip-trunking
- **Sarvam AI Docs**: https://docs.sarvam.ai/
- **Google Gemini API**: https://ai.google.dev/docs
- **LiveKit SIP Guide**: https://docs.livekit.io/agents/start/telephony/

## 🤝 Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

See [LICENSE](LICENSE) file for details.

## 💬 Support

- **Issues**: Open an issue on GitHub
- **Discussions**: Use GitHub Discussions
- **LiveKit Support**: https://livekit.io/support
- **Twilio Support**: https://support.twilio.com

---

**Built with ❤️ using LiveKit, Sarvam AI, and Google Gemini**
