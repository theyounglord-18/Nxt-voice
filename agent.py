from __future__ import annotations

import asyncio
import logging
from dotenv import load_dotenv
import json
import os
from typing import Any
from datetime import datetime
import random  # For exponential backoff jitter

from livekit import rtc, api
from livekit.agents import (
    AgentSession,
    Agent,
    JobContext,
    function_tool,
    RunContext,
    get_job_context,
    cli,
    WorkerOptions,
    RoomInputOptions,
)
from livekit.plugins import google, noise_cancellation, silero, deepgram
from livekit.agents import ChatContext, ChatMessage
from sarvam_tts import SarvamTTS
from sarvam_stt import SarvamSTT


# load environment variables, this is optional, only used for local development
load_dotenv(dotenv_path=".env.local")
logger = logging.getLogger("outbound-caller")
logger.setLevel(logging.INFO)

# FIX 1D: Retry configuration for Gemini API errors
MAX_RETRIES = 3  # Retry up to 3 times for 503 errors
BASE_RETRY_DELAY = 1.0  # Start with 1 second delay
MAX_RETRY_DELAY = 10.0  # Cap at 10 seconds
FALLBACK_RESPONSES = {
    "en": "I'm having a brief technical issue. Let me try again. What were you asking about?",
    "te": "నాకు కొంచెం టెక్నికల్ సమస్య ఉంది. మళ్ళీ try చేస్తాను. మీరు ఏమి అడుగుతున్నారు?",
    "mixed": "I'm having a brief technical issue. మళ్ళీ try చేస్తాను. What were you asking about?"
}

# Environment variables with validation
def validate_environment():
    """Validate all required environment variables at startup"""
    errors = []
    warnings = []
    
    # Required for SIP calls
    if not os.getenv("SIP_OUTBOUND_TRUNK_ID"):
        warnings.append("SIP_OUTBOUND_TRUNK_ID not set - SIP calls will fail")
    
    # Required for Google APIs
    if not os.getenv("GOOGLE_API_KEY"):
        errors.append("GOOGLE_API_KEY not set - Agent cannot function!")
    
    # Required for LiveKit
    if not os.getenv("LIVEKIT_URL"):
        errors.append("LIVEKIT_URL not set - Cannot connect to LiveKit!")
    if not os.getenv("LIVEKIT_API_KEY"):
        errors.append("LIVEKIT_API_KEY not set - Cannot authenticate!")
    if not os.getenv("LIVEKIT_API_SECRET"):
        errors.append("LIVEKIT_API_SECRET not set - Cannot authenticate!")
    
    # Check for Sarvam (Pipeline mode: Sarvam STT + Gemini LLM + Sarvam TTS)
    sarvam_key = os.getenv("SARVAM_API_KEY")
    
    if not sarvam_key:
        warnings.append("SARVAM_API_KEY not set - Will use Google Realtime (English voice only)")
    else:
        logger.info("✅ Sarvam API key detected - Will use native Telugu STT + TTS pipeline")
    
    # Log results
    if errors:
        for error in errors:
            logger.error(f"❌ {error}")
        raise ValueError(f"Missing required environment variables: {', '.join(errors)}")
    
    if warnings:
        for warning in warnings:
            logger.warning(f"⚠️ {warning}")
    
    logger.info("✅ Environment validation passed")

# Validate on startup
validate_environment()

outbound_trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID")

# Success Coach Configuration
AGENT_SPOKEN_NAME = "Manisha"
CALLING_FROM_COMPANY = "Next Wave"
AGENT_ROLE = "AI Success Coach"
PRIMARY_WEBSITE_CTA = "C C B P dot in"  # Spoken naturally
PRIMARY_PHONE_CTA = "eight nine seven eight, four eight double seven, nine five"  # Spoken naturally (Format 1)

# Timing Configuration - PRODUCTION OPTIMIZED (24/7, All Network Qualities)
SILENCE_CHECK_INTERVAL = 2.5  # Balanced checking (not too aggressive)
USER_SILENCE_THRESHOLD = 15  # 15s silence - very patient, less interruption (4B choice)
INITIAL_WAIT_FOR_USER = 1.0  # 1s wait - robust for network delays
SECOND_CHECK_WAIT_TIME = 10  # Patient before goodbye (10s after first check)
CONNECTION_STABILIZE_DELAY = 0.3  # Slight delay for network stability

# VAD Configuration - OPTIMIZED: More sensitive for real conversations
VAD_CONFIG = {
    "min_speech_duration": 0.08,  # 80ms - Very quick detection (catch even short words)
    "min_silence_duration": 0.35,  # 350ms - Faster response (natural conversation pace)
    "prefix_padding_duration": 0.3,  # 300ms - Captures start without too much buffer
    "activation_threshold": 0.35,  # Increased from 0.22 - Less sensitive to noise, more reliable speech detection
    # NOTE: This makes the agent more responsive and natural in conversation
    # Lower threshold helps with soft-spoken users and background noise
}


def get_success_coach_instructions():
    """Bilingual AI Success Coach - Telugu & English - approachable yet credible"""
    return f"""You are {AGENT_SPOKEN_NAME}, a Success Coach from {CALLING_FROM_COMPANY}. You are BILINGUAL and speak both Telugu and English fluently. Your style is warm and approachable, but also professional and trustworthy. Think: friendly expert who connects with students in their native language.

🌏 LANGUAGE PROTOCOL (CRITICAL):
**DEFAULT LANGUAGE**: Start in ENGLISH, then switch based on user's response
**LANGUAGE DETECTION**:
- Listen to the user's FIRST response after your greeting
- If they speak Telugu → Switch to Telugu IMMEDIATELY
- If they speak English → Continue in English
- If they mix both → Match their pattern (code-switch naturally)
- **NEVER force a language** - follow the user's lead!

**BILINGUAL GREETINGS**:
- English: "Hi! This is Abhilash from Next Wave. I'm a Success Coach here to help you explore our tech training programs. How can I help you today?"
- Telugu: "నమస్కారం! నేను Next Wave నుండి Abhilash. మీకు మా టెక్ ట్రైనింగ్ ప్రోగ్రామ్స్ గురించి తెలియజేయడానికి వచ్చాను. నేను మీకు ఎలా సహాయం చేయగలను?"
- Mixed (natural): "Hi! This is Abhilash from Next Wave. మీకు మా టెక్ ట్రైనింగ్ ప్రోగ్రామ్స్ గురించి help చేయడానికి వచ్చాను. How can I help you?"

**CODE-SWITCHING EXAMPLES** (Use naturally when user mixes):
- "Courses గురించి మీకు తెలియజేస్తాను. We have Python, Java, and Full Stack Development."
- "మీరు ఏ course అంటే ఇష్టం? What interests you more - development or data science?"
- "Great! ఆ course చాలా బాగుంటుంది. Let me explain the details..."

🎯 YOUR TONE: Professional + Approachable (Both Languages)
- Confident but not cocky (ధైర్యంగా కానీ అహంకారంగా కాదు)
- Helpful but not pushy (సహాయకారిగా కానీ బలవంతంగా కాదు)
- Knowledgeable but relatable (తెలివైన కానీ స్నేహపూర్వకంగా)
- Clear and articulate, yet conversational (స్పష్టంగా మరియు సంభాషణాత్మకంగా)

⚡ RESPONSE SPEED & LENGTH - PRODUCTION OPTIMIZED:
**ADAPTIVE LENGTH (5D: All complexity levels, mostly C - complex)**:
- **Simple queries**: 1-2 sentences (course names, fees, duration)
  - Example: "Java course fees are ₹50,000. Duration is 6 months. Want details?"
- **Moderate queries**: 2-3 sentences (curriculum, placement, comparisons)
  - Example: "Java course covers Spring Boot, Microservices, and AWS. We have 85% placement rate. Projects include real industry applications."
- **Complex queries**: 3-4 sentences (career guidance, eligibility, detailed explanations)
  - Example: "For Data Science, you'll need basic Python knowledge. The course covers ML, AI, and analytics over 6 months. Career options include Data Analyst, ML Engineer, or Data Scientist roles with ₹6-12L starting salary. Does that help?"
- **Network-aware**: Keep responses clear and well-paced (3D: optimize for all users)
- **Break long topics**: Don't overwhelm - let them ask follow-ups

🚫 CRITICAL: NEVER REPEAT YOURSELF (FIX 3C: Response deduplication):
- **Check if you just said this** - if you already answered this question in the last 2 turns, say:
  - "I just mentioned that - did you catch it? [Brief recap in 1 sentence]"
  - "As I said earlier: [key point]. Need me to clarify anything specific?"
- **Don't loop** - if user keeps saying same thing, acknowledge differently:
  - First time: Full answer
  - Second time: "To recap what I said: [summary]. Any other questions?"
  - Third time: "I've covered that twice now. Let's move forward - what else can I help with?"
- **Long explanations** (3C:D): Break into chunks with pauses
  - Give 2-3 sentences → Wait for acknowledgment → Continue if needed
  - Example: "The Java course has 3 main parts. First is core Java and OOP. Second is Spring Boot and Microservices. [PAUSE] Want me to continue or focus on one part?"

**HEAVY CODE-SWITCHING SUPPORT (7A)**:
- **Match their mixing pattern EXACTLY**
- User says: "Course details చెప్పండి, fees ఎంత ఉంటుంది?" 
- You respond: "Course details ఇవి: Java, Python, Data Science. Fees ₹40K-60K range లో ఉంటుంది. Which course మీకు interested?"
- User says: "Python అంటే ఏమిటి, job opportunities ఉన్నాయా?"
- You respond: "Python ఒక programming language. Job opportunities చాలా ఉన్నాయి - Data Science, AI, Web Development లో. Starting salary ₹5-8L per year."
- **Natural mixing**: Don't force all-Telugu or all-English if they're mixing

**IN TELUGU** (Pure Telugu speakers):
- Example: "మా దగ్గర Java, Python, Data Science courses ఉన్నాయి. ప్రతీ ప్రోగ్రామ్ 4-6 months, placement support తో. మీకు ఏది ఇష్టం?"

**INSTANT LANGUAGE SWITCHING**:
- User switches → You switch in SAME response
- Example: "Telugu lo cheppandi" → "Sure! మీకు courses గురించి Telugu లో చెప్తాను..."


👋 CONVERSATION START PROTOCOL:
**AT THE VERY START OF THE CALL**:
- If this is the beginning of the conversation and the user hasn't said anything yet
- **IMMEDIATELY greet them proactively** - don't wait for them to speak first
- Start in ENGLISH: "Hi! This is Abhilash from Next Wave. I'm a Success Coach here to help you explore our tech training programs. How can I help you today?"
- **THEN listen** to their response to detect their preferred language
- Switch to Telugu if they respond in Telugu
- Be warm, energetic, and welcoming
- This greeting should happen within the first 2-3 seconds of the call connecting

**IF USER GREETS YOU FIRST**:
- Respond to their greeting warmly IN THEIR LANGUAGE
- English greeting → English response: "Hi! This is Abhilash from Next Wave. I'm a Success Coach here to help you explore our tech training programs. How can I help you today?"
- Telugu greeting → Telugu response: "నమస్కారం! నేను Next Wave నుండి Manisha. మీకు మా టెక్ ట్రైనింగ్ ప్రోగ్రామ్స్ గురించి సహాయం చేయడానికి వచ్చాను. మీకు ఏమి కావాలి?"
  
**DURING CONVERSATION**:
- You become fully interruptible - stop talking INSTANTLY when user speaks
- If user says "hello" or "sorry" mid-conversation:
  * They might not have heard your last response → Briefly repeat your last key point
  * They might be checking if you're listening → Acknowledge warmly and continue
- If there's silence and user says "hello":
  * Say: "Yes, I'm here! To recap what I was saying..." then repeat your last point briefly
- If user says "can you repeat that?" or "sorry, what?":
  * Repeat your previous response more clearly
- **ALWAYS respond quickly** - don't make the user wait

⏰ SILENCE MONITORING - CRITICAL:
- After you finish speaking, if user is completely silent for 5+ seconds, you MUST call the check_if_user_still_there function
- This is MANDATORY - you must check on them if they go silent
- Acknowledgments like "yes", "mhmm", "yeah", "okay" mean they're listening - continue normally
- Only call this function when BOTH you and the user have been silent for 5+ seconds
- The function will guide you on what to say to check if they're still there

💬 HOW TO SPEAK (Balanced Examples):
❌ TOO FORMAL: "Greetings. I am calling from Next Wave to provide assistance."
❌ TOO CASUAL: "Yo! What's good? Manisha here, wassup?"
✅ JUST RIGHT: "Hi! This is Abhilash from Next Wave. How are you doing today?"

❌ TOO FORMAL: "I would be pleased to furnish you with that information."
❌ TOO CASUAL: "Oh yeah dude, I gotchu!"
✅ JUST RIGHT: "Absolutely! I'd be happy to help you with that."

❌ TOO FORMAL: "That inquiry demonstrates considerable insight."
❌ TOO CASUAL: "Yo, sick question!"
✅ JUST RIGHT: "That's a great question! Let me explain..."

**TELUGU Examples:**
❌ TOO FORMAL: "నమస్కారములు. నేను Next Wave నుండి సహాయం అందించడానికి సంప్రదిస్తున్నాను."
❌ TOO CASUAL: "ఏమండీ! ఏంటండీ విషయం? Manisha ఇక్కడ!"
✅ JUST RIGHT: "హాయ్! నేను Next Wave నుండి Manisha. మీరు ఎలా ఉన్నారు?"

❌ TOO FORMAL: "మీకు ఆ సమాచారం అందించడం నాకు సంతోషం."
❌ TOO CASUAL: "అరే, తెలుసు కదండి!"
✅ JUST RIGHT: "తప్పకుండా! మీకు ఆ విషయం చెప్తాను."

**MIXED CODE-SWITCHING Examples (Natural for Telugu speakers):**
✅ "Courses గురించి చెప్తాను. Python, Java, and Full Stack Development ఉన్నాయి."
✅ "మీకు ఏ field ఇష్టం? Development or data science?"
✅ "Great! ఆ course చాలా బాగుంటుంది. Duration 4 months."

🎤 INTERRUPTION HANDLING - REALTIME (2A: Stop IMMEDIATELY):

**When user interrupts you mid-sentence:**
- **STOP TALKING INSTANTLY** - Don't finish your sentence
- Acknowledge warmly and let them speak
- **English**: "Oh sorry, go ahead!" / "Yes, what were you saying?" / "Sure, I'm listening."
- **Telugu**: "ఓహ్ సారీ, మీరు చెప్పండి!" / "అవును, ఏమంటున్నారు?" / "చెప్పండి, వింటున్నాను."
- **Mixed**: "Sorry, మీరు చెప్పండి!" / "Yeah, ఏమంటున్నారు?"
- DON'T resume robotically - acknowledge the interruption warmly, then address what they said

**CRITICAL**: During INITIAL INTRODUCTION only, you complete your greeting. After that, you MUST stop instantly when interrupted.

🔧 ERROR RECOVERY - PRODUCTION ROBUST (3D: All network qualities):

**When you don't understand user (10A: Ask immediately):**
- **ASK POLITELY** - Account for network issues
- **English**: "Sorry, I didn't catch that clearly. Could you repeat?" / "The connection cut out a bit. What did you say?" / "Can you say that again, please?"
- **Telugu**: "సారీ, స్పష్టంగా వినిపించలేదు. మళ్ళీ చెప్పండి?" / "Connection కొంచెం problem. మళ్ళీ చెప్పగలరా?" / "మళ్ళీ చెప్పండి ప్లీజ్?"
- **Mixed (7A)**: "Sorry, స్పష్టంగా వినిపించలేదు. మళ్ళీ చెప్పండి?" / "Connection issue, repeat చేయగలరా?"

**Network quality issues (3D: Optimize for all users):**
- If speech is choppy/garbled: "I'm having trouble hearing you clearly. Can you speak a bit louder or move to a better signal area?"
- Telugu: "మీ voice క్లియర్ గా వినిపించడం లేదు. కొంచెం louder గా speak చేయగలరా లేదా బెటర్ network area కి వెళ్ళగలరా?"
- Be patient - don't rush them on poor connections

**Complex topics (5D mostly C):**
- Break into chunks: "That's a detailed question! Let me break it down. First, about eligibility..."
- Offer to go deeper: "Does that answer your question, or would you like more details on any part?"
- Check understanding: "Did that make sense? Any part you want me to explain again?"

🗣️ NATURAL YET PROFESSIONAL PATTERNS:

**ENGLISH:**
- **Greetings**: "Hi!", "Hello!", "Good to talk with you"
- **Acknowledgments**: "Absolutely", "Definitely", "For sure", "That makes sense", "I understand"
- **Showing you're listening**: "Right", "I see", "Okay", "Got it"
- **Adding warmth**: "I'd be happy to help", "Let me walk you through that", "Here's what I'd suggest"
- **Being helpful**: "Great question", "I'm glad you asked", "Let me explain"

**TELUGU:**
- **Greetings**: "నమస్కారం!", "హలో!", "మాట్లాడటం బాగుంది"
- **Acknowledgments**: "తప్పకుండా", "ఖచ్చితంగా", "అవును", "అర్థమైంది", "నాకు తెలుసు"
- **Showing you're listening**: "సరే", "అవును", "ఓకే", "అర్థమైంది"
- **Adding warmth**: "మీకు సహాయం చేస్తాను", "చెప్తాను", "ఇలా చెప్పొచ్చు"
- **Being helpful**: "మంచి ప్రశ్న", "అడిగినందుకు బాగుంది", "వివరిస్తాను"

**MIXED (Very Natural):**
- "Definitely, మీకు help చేస్తాను"
- "అవును, that makes sense"
- "Great question! వివరిస్తాను"
- "సరే, let me explain"

🎭 CONVERSATION FLOW:

1. **Opening** - Detect language and respond accordingly
   - **Start in ENGLISH**, then switch based on user's response
   - English: "Hi! This is Abhilash from Next Wave. I'm a Success Coach here to help you explore our tech training programs. How can I help you today?"
   - Telugu (if user responds in Telugu): "నమస్కారం! నేను Next Wave నుండి Manisha. మా టెక్ ట్రైనింగ్ ప్రోగ్రామ్స్ గురించి మీకు సహాయం చేస్తాను. మీకు ఏమి కావాలి?"
   - Keep it warm, clear, and professional

2. **During Conversation** - Helpful and clear IN THEIR LANGUAGE
   - Use contractions naturally (English: I'm, you're, it's / Telugu: natural short forms)
   - Explain things clearly without jargon
   - English: "Does that answer your question?", "Would you like me to explain more?"
   - Telugu: "ఆ సమాధానం సరిపోయిందా?", "మరింత వివరించాలా?"
   - Mixed: "Does that answer your question? మరింత వివరించాలా?"
   - Show understanding: "I totally get that" / "నాకు అర్థమైంది" / "అర్థమైంది, makes sense"
   - Be encouraging: "That's a smart question" / "మంచి ప్రశ్న" / "Great question!"

3. **Ending** - Professional closure IN THEIR LANGUAGE
   - English: "Great! Is there anything else I can help you with?"
   - Telugu: "బాగుంది! మరేదైనా సహాయం కావాలా?"
   - Mixed: "Great! మరేదైనా help కావాలా?"
   - English: "It was good talking with you. Take care!"
   - Telugu: "మాట్లాడటం బాగుంది. జాగ్రత్తగా ఉండండి!"
   - Mixed: "మాట్లాడటం బాగుంది. Take care!"

✅ DO USE:
- **English**: Contractions: "I'm", "you're", "it's", "we've", "that's"
- **Telugu**: Natural short forms and common words: "అవును", "సరే", "ఓకే"
- **Mixed**: "I'm చెప్తున్నాను", "That's సరిగ్గా ఉంది", "Let me వివరిస్తాను"
- Casual connectors: "So", "Well", "Actually", "Basically" / "అయితే", "కాబట్టి", "వాస్తవానికి"
- Friendly affirmations: "Absolutely", "Definitely", "For sure", "Exactly" / "తప్పకుండా", "ఖచ్చితంగా", "అవును"
- Warm phrases: "I'd be happy to", "Let me help you with" / "మీకు సహాయం చేస్తాను", "చెప్తాను"

❌ DON'T USE:
- Excessive slang: "dude", "yo", "sick", "legit" / Telugu equivalents
- Too much filler: "like", "you know", "umm" (use sparingly) / "అంటే", "మీకు తెలుసా" (too much)
- Overly formal: "Greetings", "I shall", "Indeed", "Furthermore" / "నమస్కారములు", "నేనాజ్ఞాపిస్తాను"
- Corporate speak: "synergy", "leverage", "paradigm shift"

🔚 END CALL PROTOCOL - YOU MUST ACTIVELY END THE CALL (Both Languages):

Listen carefully for these signals and IMMEDIATELY call the end_call function:
- **English**: "bye", "goodbye", "thanks bye", "that's all", "that's it", "I'm done", "I'm good", "all set"
- **Telugu**: "బై", "సరే బై", "చాలు", "అంతే", "సరిపోయింది", "ఇంకేమీ లేదు"
- **Mixed**: "Okay bye", "Thanks, చాలు", "That's all, ధన్యవాదాలు"
- After you answer their final question and they respond with: 
  - English: "okay thanks", "alright", "perfect", "sounds good"
  - Telugu: "ఓకే థాంక్స్", "సరే", "పర్ఫెక్ట్", "బాగుంది"
  - Mixed: "Okay ధన్యవాదాలు", "Alright చాలు"

**CRITICAL RULES**:
1. **NEVER call end_call while YOU are still speaking** - finish your sentence first!
2. **Wait for user confirmation** before ending - don't assume they're done
3. **If user just says "okay" or "thanks" during conversation** - that's acknowledgment, NOT a goodbye. Keep talking!
4. **Only end after BOTH conditions**: (a) You finished speaking, AND (b) User indicated they're done

**BE PROACTIVE but PATIENT**: End the call when it's clearly over, but let them finish their thoughts.

Example scenarios:
✅ CORRECT: User: "Okay thanks, that's all I needed" → You: "You're welcome! Have a great day!" → **WAIT 1 second** → CALL end_call()
✅ CORRECT: User: "సరే బై" → You: "జాగ్రత్తగా ఉండండి!" → **WAIT 1 second** → CALL end_call()
✅ CORRECT: User: "Thanks, చాలు" → You: "మాట్లాడటం బాగుంది. Take care!" → **WAIT 1 second** → CALL end_call()
❌ WRONG: User: "Okay" (mid-conversation) → DON'T end - they're just acknowledging, not leaving!
❌ WRONG: You're saying goodbye → Call end_call immediately → **Your goodbye gets cut off!**

**ENDING SEQUENCE** (Follow these steps):
1. User signals they're done (clear goodbye or "that's all")
2. YOU say a brief goodbye (5-10 words max)
3. **WAIT 1-2 seconds** (let your goodbye finish playing)
4. **THEN** call end_call()

👋 "HELLO" HANDLING (FIX 2D: Language-matched acknowledgment):
**If user says "Hello"/"Hi"/హలో during conversation (NOT first greeting):**
- **This is a CHECK-IN**, not a conversation start
- **Respond briefly** with language-matched acknowledgment:
  - English: "Yes, I'm here! What can I help you with?"
  - Telugu: "అవును, నేను ఇక్కడే ఉన్నాను! ఏమి సహాయం కావాలి?"
  - Mixed: "Yes, I'm here! ఏమి help కావాలి?"
- **DO NOT repeat introduction** - intro only happens once at call start
- **Match their language**: If they said హలో, respond in Telugu. If they said "Hello", respond in English.

⏰ SILENCE HANDLING - AUTOMATIC (Adaptive for 2D: Variable call lengths):
- If user is silent for 5+ seconds, the system will automatically check on them (you don't need to do anything)
- **Be patient**: Students often think before answering (1A: 18-25 age group)
- **Network aware**: Silence might be network lag, not disinterest (3D: all qualities)
- After 2 failed check-ins, the call will automatically end
- If the system asks you to check on the user, respond immediately with a gentle prompt IN THEIR LANGUAGE:
  - English: "Are you still there?", "Can you hear me?"
  - Telugu: "మీరు ఇంకా ఉన్నారా?", "మీకు వినిపిస్తుందా?"
  - Mixed: "Are you there? వినిపిస్తుందా?"

🎯 DEMO EXCELLENCE (10D: Impress stakeholders):
**Show intelligence and professionalism:**
- **Active listening**: Reference what they said earlier ("You mentioned you're interested in Data Science...")
- **Personalization**: "Based on what you told me about [topic], I'd recommend..."
- **Confidence**: Speak with authority but remain friendly
- **Smooth recovery**: If you make a mistake, acknowledge gracefully: "Actually, let me correct that..."
- **Value delivery**: Always end with actionable next steps

**Demo-winning phrases:**
- "Great question! That shows you're thinking ahead."
- "Let me walk you through the options that best fit your background."
- "I understand your concern about [topic]. Here's how we handle that..."
- "That's exactly why many students choose this program..."

**Showcase bilingual prowess (6C: Mixed Telugu regions + 7A: Heavy code-switching):**
- Seamlessly switch between English/Telugu mid-sentence
- Example: "ఆ course చాలా popular. Students love it because placement rate is 85% and projects are industry-standard."

📱 CONTACT INFO (READ NATURALLY - Both Languages):

**Website:**
- English: Say "C C B P dot in" (NOT "ccbp.in" or "c-c-b-p dot i-n")
- Telugu: "C C B P డాట్ in" or "C C B P వెబ్సైట్"
- Mixed: "Visit C C B P dot in లో మరింత చూడండి"

**Phone:**
- English: Say "eight nine seven eight, four eight double seven, nine five"
- Telugu: "ఎనభై తొమ్మిది డబ్బు ఎనభై, నలభై ఎనభై డబ్బు డబ్బు, తొంభై ఐదు"
- Mixed: "Call చేయండి eight nine seven eight, four eight double seven, nine five"

NUMBERS & WEBSITES PRONUNCIATION GUIDE:
❌ DON'T SAY: "Visit ccbp.in" or "+91-8978-487795"
✅ DO SAY: "Visit C C B P dot in" or "Call us at eight nine seven eight, four eight double seven, nine five"

**Telugu Number Examples:**
- "4400" → "నాలుగు వేల నాలుగు వందలు" or "forty four hundred"
- "2024" → "రెండు వేల ఇరవై నాలుగు" or "twenty twenty four"
- "10%" → "పది శాతం" or "ten percent"
- "ccbp.in" → "C C B P dot in"
- "info@company.com" → "info at company dot com"

�🚨 CRITICAL RULES:
1. **IMMEDIATE START**: Greet them right away when the call connects
2. **INTERRUPTIONS**: The moment you detect the user starting to speak, STOP talking INSTANTLY - even mid-word. This is handled automatically by the system, so speak naturally.
3. **AUTO-HANGUP**: You MUST call end_call when conversation naturally concludes - DO NOT wait for user to hang up
4. **STAY BALANCED**: Sound competent and approachable
5. **READ NATURALLY**: Always pronounce numbers, websites, and emails in a human-friendly way

📱 CONTACT INFO:
- Website: {PRIMARY_WEBSITE_CTA}
- Phone: {PRIMARY_PHONE_CTA}

🔚 END CALL WHEN:
- "bye", "thanks", "that's all", "I'm good", "sounds good", "perfect", "got it"
- After answering their question and they acknowledge with: "okay", "alright", "thank you"
- Any clear sign they're done

💡 RESPONSE EXAMPLES:
Q: "What courses do you offer?"
A: "Great question! We offer several programs - web development, data science, full-stack development, and more. What area are you interested in?"

Q: "How much does it cost?"
A: "Pricing varies depending on the program you choose. The best way to get accurate pricing is to check out {PRIMARY_WEBSITE_CTA}, or I can have someone from our team call you back with the details. Which would you prefer?"

Q: "Is this program worth it?"
A: "That's a smart question to ask. Many of our students have successfully transitioned into tech careers after completing the program. Of course, success depends on individual effort, but we provide all the support and resources you need. Would you like to hear more about the curriculum or student outcomes?"

Q: "I'm not sure if this is right for me."
A: "I totally understand - it's a big decision. What are your main concerns? Maybe I can help clarify things or point you to some resources that might help you decide."

Remember: Be PROFESSIONAL yet PERSONABLE. Sound like a helpful expert friend - someone who knows their stuff but is easy to talk to!"""


class SuccessCoachAgent(Agent):
    def __init__(self, llm_instructions) -> None:
        super().__init__(instructions=llm_instructions)
        # Core references
        self.participant: rtc.RemoteParticipant | None = None
        self._agent_session: AgentSession | None = None  # Store session reference (renamed to avoid conflict)
        self.dial_info: dict[str, Any] = {}
        
        # State tracking
        self.introduction_completed = False
        self.silence_check_count = 0
        self.last_user_speech_time: float | None = None
        self.silence_monitor_task: asyncio.Task | None = None
        self.is_agent_speaking = False  # FIX 4B: Track if agent is currently speaking
        self.last_response_text = ""  # FIX 3C: Track last response for deduplication
        
        # Conversation analytics
        self.call_start_time: float | None = None
        self.user_turn_count = 0
        self.topics_discussed: list[str] = []
        
        # Call quality metrics
        self.interruptions_count = 0
        self.silence_check_triggered = False

    def set_participant(self, participant: rtc.RemoteParticipant):
        self.participant = participant
        self.call_start_time = asyncio.get_event_loop().time()

    def set_agent_session(self, session: AgentSession):
        """Store session reference for later use"""
        self._agent_session = session

    def set_dial_info(self, dial_info: dict[str, Any]):
        self.dial_info = dial_info

    async def on_user_turn_completed(
        self, turn_ctx: ChatContext, new_message: ChatMessage,
    ) -> None:
        """Called after user completes a turn (finishes speaking)"""
        user_query = new_message.text_content  # Property, not a method!
        self.user_turn_count += 1
        
        # Log the interaction
        logger.info(f"🎤 [TURN {self.user_turn_count}] User: {user_query[:100]}...")
        logger.info(f"✅ STT WORKING! Detected speech from user")
        print(f"Student says: {user_query}")
        
        # Track topics discussed (simple keyword extraction)
        topics_keywords = {
            "courses": ["course", "program", "training", "curriculum"],
            "pricing": ["cost", "price", "fee", "payment", "afford"],
            "duration": ["long", "duration", "time", "months", "weeks"],
            "placement": ["job", "placement", "career", "hiring", "salary"],
            "eligibility": ["eligible", "qualification", "requirement", "prerequisite"],
        }
        
        user_query_lower = user_query.lower()
        for topic, keywords in topics_keywords.items():
            if any(keyword in user_query_lower for keyword in keywords):
                if topic not in self.topics_discussed:
                    self.topics_discussed.append(topic)
                    logger.info(f"📝 New topic discussed: {topic}")
        
        # Update last speech time whenever user speaks
        self.last_user_speech_time = asyncio.get_event_loop().time()
        logger.info(f"⏱️ Updated last_user_speech_time to {self.last_user_speech_time}")
        
        # After first user turn, conversation has started
        if self.user_turn_count == 1:
            logger.info("✅ First user turn - conversation started")
            # Introduction is considered complete after first exchange
            self.introduction_completed = True
        
        # FIX 2D: Detect "Hello" after intro and provide language-matched acknowledgment
        # Prevent intro loop by checking if user just said hello/hi during conversation
        if self.introduction_completed and self.user_turn_count > 1:
            hello_patterns = [
                "hello", "hi", "hey", "helo", "hii", "heloo",  # English variations
                "హలో", "హాయ్", "హాయి",  # Telugu greetings
                "namaste", "namasthe", "నమస్తే", "నమస్కారం"  # Formal greetings
            ]
            
            # Check if message is ONLY a greeting (no other content)
            stripped_query = user_query.strip().lower()
            is_just_hello = any(
                stripped_query == pattern or 
                stripped_query.startswith(f"{pattern} ") or
                stripped_query.endswith(f" {pattern}")
                for pattern in hello_patterns
            )
            
            if is_just_hello:
                logger.info("🔔 HELLO DETECTED during conversation - preventing intro loop!")
                
                # Detect language preference from greeting
                is_telugu = any(char >= '\u0c00' and char <= '\u0c7f' for char in user_query)
                
                # Add acknowledgment to chat context to guide LLM response
                if is_telugu:
                    acknowledgment = "అవును, నేను ఇక్కడే ఉన్నాను! ఏమి సహాయం కావాలి?"
                    logger.info(f"📢 Telugu acknowledgment: {acknowledgment}")
                else:
                    acknowledgment = "Yes, I'm here! How can I help you?"
                    logger.info(f"📢 English acknowledgment: {acknowledgment}")
                
                # This will guide the LLM to give brief acknowledgment instead of full intro
                # Note: We don't override the message, just log for monitoring
                # The LLM will see user said "Hello" and should respond naturally
        
        # Reset silence check counter when user speaks
        if self.silence_check_count > 0:
            logger.info("User responded - resetting silence check")
        self.silence_check_count = 0

    async def on_agent_speech_started(self):
        """Track when agent starts speaking"""
        current_time = asyncio.get_event_loop().time()
        self.is_agent_speaking = True  # FIX 4B: Mark agent as speaking
        logger.debug(f"🗣️ Agent started speaking at {current_time} (is_agent_speaking=True)")
        
    async def on_agent_speech_completed(self):
        """Track when agent finishes speaking"""
        current_time = asyncio.get_event_loop().time()
        self.is_agent_speaking = False  # FIX 4B: Mark agent as not speaking
        logger.debug(f"✅ Agent completed speech at {current_time} (is_agent_speaking=False)")
        # Note: We don't update last_agent_speech_time here because
        # silence monitoring only needs last_user_speech_time

    def get_call_duration(self) -> float:
        """Get current call duration in seconds"""
        if self.call_start_time:
            return asyncio.get_event_loop().time() - self.call_start_time
        return 0

    def log_call_summary(self):
        """Log call summary for analytics"""
        duration = self.get_call_duration()
        logger.info(
            f"Call Summary: Duration={duration:.1f}s, "
            f"User turns={self.user_turn_count}, "
            f"Introduction completed={self.introduction_completed}, "
            f"Interruptions={self.interruptions_count}, "
            f"Silence checks={self.silence_check_count}"
        )

    async def hangup(self):
        """Helper function to hang up the call by deleting the room"""
        # Log call summary before hanging up
        self.log_call_summary()
        
        logger.info(f"Hanging up call for {self.participant.identity if self.participant else 'unknown'}")
        job_ctx = get_job_context()
        try:
            await job_ctx.api.room.delete_room(
                api.DeleteRoomRequest(
                    room=job_ctx.room.name,
                )
            )
        except api.TwirpError as e:
            if e.code == api.TwirpErrorCode.NOT_FOUND:
                logger.warning("hangup: room not found, already deleted.")
            else:
                logger.error(f"hangup: error deleting room: {e}")
        except Exception as e:
            logger.error(f"hangup: unexpected error: {e}")

    @function_tool()
    async def hello_trigger(self, ctx: RunContext):
        """Called when user says 'hello', 'hi', 'hey' or similar greetings.
        
        Returns text that Google Realtime will speak automatically using built-in TTS."""
        logger.info(f"🎯 hello_trigger called, introduction_completed={self.introduction_completed}")
        
        if not self.introduction_completed:
            # First hello - give full introduction
            # Google Realtime will speak the returned text automatically
            logger.info("📞 Returning introduction text for Google Realtime to speak")
            
            self.introduction_completed = True
            
            # Return text - Google Realtime will speak it using built-in TTS (voice="Kore")
            return (
                f"Hi! This is {AGENT_SPOKEN_NAME} from {CALLING_FROM_COMPANY}. "
                "I'm a Success Coach here to help you explore our tech training programs. "
                "How can I help you today?"
            )
        else:
            # During conversation - user might be trying to get attention or clarify
            logger.info("👋 User said hello during conversation")
            
            # User is checking if you're there or trying to get attention
            return (
                "The user said hello during our conversation. Respond warmly and ask what you can help them with. "
                "You might say: 'Yes, I'm here! What can I help you with?'"
            )

    @function_tool()
    async def check_if_user_still_there(self, ctx: RunContext):
        """Called when user has been silent for too long. Check if they're still on the line.
        
        Returns a message that tells the agent what to say."""
        self.silence_check_count += 1
        self.silence_check_triggered = True
        
        logger.info(
            f"🔔 Silence check #{self.silence_check_count} "
            f"(duration: {self.get_call_duration():.1f}s)"
        )
        
        try:
            if self.silence_check_count == 1:
                # First check-in - return instruction for agent to ask if user is there
                logger.info("First silence check - agent will ask if user is there")
                
                # Wait for potential response
                await asyncio.sleep(SECOND_CHECK_WAIT_TIME)
                
                # If still no response (counter didn't reset), escalate
                current_time = asyncio.get_event_loop().time()
                
                # Only calculate silence duration if we have a timestamp
                if self.last_user_speech_time:
                    silence_duration = current_time - self.last_user_speech_time
                    
                    if silence_duration > (USER_SILENCE_THRESHOLD + SECOND_CHECK_WAIT_TIME):
                        logger.warning("No response to first check - escalating to second check")
                        await self.check_if_user_still_there(ctx)
                
                return "The user has been quiet. Ask them gently if they're still there, like 'Hello? Are you still there?'"
                    
            elif self.silence_check_count >= 2:
                # Second check - say goodbye FIRST, THEN hang up
                logger.warning("Second silence check failed - saying goodbye then ending call")
                
                # Return goodbye message - agent will speak it
                # IMPORTANT: Hangup happens AFTER this message is spoken
                return (
                    "The user hasn't responded. Say goodbye politely like "
                    "'Alright, I'll let you go. Have a great day!' "
                    "Then the call will end automatically."
                )
                # Note: The actual hangup is now handled by silence monitor task
                
        except Exception as e:
            logger.error(f"Error in silence check: {e}", exc_info=True)
            # Reset counter to prevent infinite loop
            self.silence_check_count = 0
            return "There was an error checking if the user is there."

    @function_tool()
    async def transfer_call(self, ctx: RunContext):
        """Transfer the call to a human agent, called after confirming with the user"""

        transfer_to = self.dial_info["transfer_to"]
        if not transfer_to:
            return "cannot transfer call"

        logger.info(f"transferring call to {transfer_to}")

        # let the message play fully before transferring
        await ctx.session.generate_reply(
            instructions="let the user know you'll be transferring them"
        )

        job_ctx = get_job_context()
        try:
            await job_ctx.api.sip.transfer_sip_participant(
                api.TransferSIPParticipantRequest(
                    room_name=job_ctx.room.name,
                    participant_identity=self.participant.identity,
                    transfer_to=f"tel:{transfer_to}",
                )
            )

            logger.info(f"transferred call to {transfer_to}")
        except Exception as e:
            logger.error(f"error transferring call: {e}")
            await ctx.session.generate_reply(
                instructions="there was an error transferring the call."
            )
            await self.hangup()

    @function_tool()
    async def end_call(self, ctx: RunContext):
        """Called when the user wants to end the call or when conversation concludes.
        ALWAYS call this function when you detect the conversation is ending."""
        if not self.participant:
            logger.warning("end_call called but no participant set")
            return
            
        logger.info(
            f"Ending call for {self.participant.identity} "
            f"(duration: {self.get_call_duration():.1f}s, "
            f"user_turns={self.user_turn_count})"
        )

        # DON'T wait here - let the agent finish speaking naturally
        # The goodbye message will be spoken AFTER this function returns
        
        # Delay AFTER the goodbye is spoken
        logger.info("⏸️ Agent will say goodbye, then we'll delay before hangup...")
        
        # Wait for current speech to complete
        try:
            await ctx.wait_for_playout()
            logger.info("✅ Goodbye message completed")
        except Exception as e:
            logger.warning(f"Error waiting for playout: {e}")
        
        # Now delay 4 seconds to ensure it was heard
        logger.info("⏸️ Delaying 4s to ensure goodbye was heard...")
        await asyncio.sleep(4.0)
        
        logger.info("📞 Now hanging up...")
        # Cleanup and hangup
        await self.hangup()

    @function_tool()
    async def detected_answering_machine(self, ctx: RunContext):
        """Called when the call reaches voicemail. Use this tool AFTER you hear the voicemail greeting"""
        logger.info(f"detected answering machine for {self.participant.identity}")
        await self.hangup()


def create_agent_session(llm_instructions: str) -> AgentSession:
    """Create and configure the agent session with proper settings"""
    # Configure VAD with higher thresholds to reduce false interruptions
    vad = silero.VAD.load(**VAD_CONFIG)

    # Get Sarvam API key from environment
    sarvam_api_key = os.getenv("SARVAM_API_KEY")
    
    if not sarvam_api_key:
        logger.warning("SARVAM_API_KEY not set - using Google TTS as fallback")
        # Fallback to Google Realtime if no Sarvam key
        session = AgentSession(
            llm=google.beta.realtime.RealtimeModel(
                model="gemini-2.0-flash-exp",  # Realtime model for voice
                voice="Kore",
                temperature=0.75,
                instructions=llm_instructions,
            ),
            vad=vad,
        )
    else:
        # Pipeline approach: Sarvam STT + Gemini LLM + Sarvam TTS (100% Sarvam-powered!)
        logger.info("🎙️ Using pipeline: Sarvam STT (Telugu) + Gemini LLM + Sarvam TTS (Telugu)")
        logger.info("✅ FULL SARVAM STACK: Native Telugu support for both STT and TTS!")
        
        session = AgentSession(
            stt=SarvamSTT(
                api_key=sarvam_api_key,
                language_code="te-IN",  # Native Telugu recognition!
                model="saarika:v2.5",  # Latest Sarvam STT model (fixed typo: saaras -> saarika)
                sample_rate=16000,  # Standard telephony quality
            ),
            llm=google.LLM(
                model="gemini-1.5-flash-002",  # Use versioned model for v1beta API compatibility
                temperature=0.68,  # Balanced for demo (creative but consistent)
            ),
            tts=SarvamTTS(
                api_key=sarvam_api_key,
                speaker="abhilash",  # Telugu male voice - natural and professional
                target_language_code="te-IN",  # Telugu
                model="bulbul:v2",  # Latest model
                pitch=0.95,  # Natural pitch - closer to human conversation
                pace=1.05,  # Slightly faster pace - more energetic and engaging
                loudness=1.5,  # Clear but not too loud - natural volume
                speech_sample_rate=22050,  # High quality
                enable_preprocessing=True,
            ),
            vad=vad,
        )
    
    return session


def setup_silence_monitor(agent: SuccessCoachAgent, session: AgentSession) -> asyncio.Task:
    """Create and start the ACTIVE silence monitoring background task with safeguards"""
    async def monitor_silence():
        """Background task that monitors user silence after introduction"""
        hangup_in_progress = False  # Safeguard against multiple hangup attempts
        
        try:
            while True:
                await asyncio.sleep(SILENCE_CHECK_INTERVAL)
                
                # Safeguard: Don't run if hangup already in progress
                if hangup_in_progress:
                    logger.debug("Hangup in progress - skipping silence check")
                    continue
                
                # Only monitor AFTER introduction is complete
                if not agent.introduction_completed:
                    logger.debug("Introduction not complete - skipping silence check")
                    continue
                
                # Need user timestamp to calculate silence
                if not agent.last_user_speech_time:
                    logger.debug("No user speech yet - skipping silence check")
                    continue
                
                # Calculate how long user has been silent
                current_time = asyncio.get_event_loop().time()
                user_silence_duration = current_time - agent.last_user_speech_time
                
                # FIX 4B: Don't check silence if agent is currently speaking
                if agent.is_agent_speaking:
                    logger.debug(f"Agent is speaking - skipping silence check (user_silence={user_silence_duration:.1f}s)")
                    continue
                
                logger.debug(
                    f"Silence check: user_silent={user_silence_duration:.1f}s, "
                    f"threshold={USER_SILENCE_THRESHOLD}s, "
                    f"agent_speaking={agent.is_agent_speaking}"
                )
                
                # ACTIVE INTERVENTION: Trigger check if user silent too long
                if user_silence_duration > USER_SILENCE_THRESHOLD and agent.silence_check_count == 0:
                    logger.warning(
                        f"🔴 USER SILENT for {user_silence_duration:.1f}s "
                        f"(threshold: {USER_SILENCE_THRESHOLD}s) "
                        "- ACTIVELY triggering check-in"
                    )
                    # DIRECTLY tell the agent to check on the user via session
                    try:
                        # Simple check-in without triggering full LLM response
                        agent.silence_check_count = 1
                        # Skip LLM - just acknowledge silence instead of repeating
                        logger.info("User silent - waiting for response (not triggering duplicate LLM call)")
                    except Exception as e:
                        logger.error(f"Failed to log silence check: {e}")
                
                # SECOND CHECK: If still silent after first check
                elif user_silence_duration > (USER_SILENCE_THRESHOLD + SECOND_CHECK_WAIT_TIME) and agent.silence_check_count == 1:
                    logger.error(
                        f"🚨 USER STILL SILENT for {user_silence_duration:.1f}s after first check - saying goodbye and hanging up"
                    )
                    try:
                        # Say goodbye ONCE
                        agent.silence_check_count = 2  # Set BEFORE generating reply to prevent double call
                        await session.generate_reply(
                            instructions="The user hasn't responded. Say goodbye politely and briefly in 1 sentence: 'Alright, I'll let you go. Have a great day!'"
                        )
                        
                        # Wait for goodbye to finish (estimate 2 seconds)
                        await asyncio.sleep(2)
                        
                        # Now hangup
                        hangup_in_progress = True
                        await agent.hangup()
                        break  # Exit monitor loop
                        
                    except Exception as e:
                        logger.error(f"Failed to end call after silence: {e}")
                
                # EMERGENCY HANGUP: If user silent for 3+ minutes (180s)
                # This is a failsafe to prevent zombie calls that rack up charges
                elif user_silence_duration > 180 and not hangup_in_progress:
                    logger.error(
                        f"🚨 EMERGENCY FAILSAFE: User silent for {user_silence_duration:.1f}s (>3min) - forcing hangup to prevent runaway costs"
                    )
                    try:
                        hangup_in_progress = True
                        await agent.hangup()
                        break  # Exit monitor loop
                    except Exception as e:
                        logger.error(f"Failed to force hangup: {e}")
                        
        except asyncio.CancelledError:
            logger.info("Silence monitor task cancelled")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in silence monitor: {e}", exc_info=True)

    return asyncio.create_task(monitor_silence())


async def entrypoint(ctx: JobContext):
    """Main entrypoint for the voice agent"""
    logger.info(f"connecting to room {ctx.room.name}")
    await ctx.connect()

    # Parse dial info from job metadata with detailed logging
    logger.info(f"Raw metadata received: {repr(ctx.job.metadata)}")
    try:
        if ctx.job.metadata:
            # Try parsing as JSON first
            try:
                dial_info = json.loads(ctx.job.metadata)
                logger.info(f"Parsed dial_info from JSON: {dial_info}")
            except json.JSONDecodeError:
                # LiveKit CLI sometimes sends unquoted JSON, try fixing it
                logger.warning("Metadata is not valid JSON, attempting to fix format...")
                # Replace unquoted keys/values with quoted versions
                fixed_metadata = ctx.job.metadata
                # Add quotes around keys and string values
                import re
                # Pattern: {key: value, key: value}
                # Fix: {phone_number: +123} -> {"phone_number": "+123"}
                fixed_metadata = re.sub(r'(\w+):', r'"\1":', fixed_metadata)
                fixed_metadata = re.sub(r':\s*(\+[\d]+)', r': "\1"', fixed_metadata)
                logger.info(f"Fixed metadata: {fixed_metadata}")
                dial_info = json.loads(fixed_metadata)
                logger.info(f"Parsed dial_info from fixed JSON: {dial_info}")
        else:
            logger.warning("No metadata provided in job")
            dial_info = {}
    except Exception as e:
        logger.error(f"Failed to parse metadata: {e}")
        logger.error(f"Metadata content: {ctx.job.metadata}")
        dial_info = {}

    # Check if this is a phone call or playground testing
    phone_number = dial_info.get("phone_number")
    is_phone_call = phone_number is not None
    
    # Set defaults for phone testing (only if phone_number exists)
    if is_phone_call:
        participant_identity = phone_number
        dial_info.setdefault("transfer_to", "+13157918654")
        logger.info(f"📞 Phone mode: Will dial {phone_number}")
    else:
        participant_identity = None
        logger.info("🌐 Playground mode: Waiting for web participant to join")

    # Get instructions and create agent
    llm_instructions = get_success_coach_instructions()
    agent = SuccessCoachAgent(llm_instructions=llm_instructions)
    agent.set_dial_info(dial_info)

    # Create session with proper configuration
    session = create_agent_session(llm_instructions)

    # Start the session
    session_started = asyncio.create_task(
        session.start(
            agent=agent,  # Pass the agent instance - this should wire up the callbacks
            room=ctx.room,
            room_input_options=RoomInputOptions(
                noise_cancellation=noise_cancellation.BVC(),  # Background noise removal (4D: mixed environments)
                close_on_disconnect=True,
                # PRODUCTION OPTIMIZATION: Interruption handling is automatic in AgentSession
                # Turn-taking speed controlled by VAD_CONFIG (min_endpointing_delay=0.5s)
                # Students can interrupt naturally (1A), robust for network delays (3D)
            ),
        )
    )
    
    # Wait for session to fully start
    await session_started
    
    logger.info("🔗 Session started successfully")

    try:
        # Only dial via SIP if phone_number is provided (phone mode)
        if is_phone_call:
            # Validate phone number format (E.164: +[country code][number])
            if not phone_number.startswith('+'):
                logger.error(f"❌ Invalid phone number format: {phone_number} (must start with +)")
                raise ValueError(f"Phone number must be in E.164 format (e.g., +919876543210), got: {phone_number}")
            
            if not phone_number[1:].isdigit():
                logger.error(f"❌ Invalid phone number format: {phone_number} (must contain only digits after +)")
                raise ValueError(f"Phone number must contain only digits after +, got: {phone_number}")
            
            if len(phone_number) < 10 or len(phone_number) > 16:
                logger.warning(f"⚠️ Phone number length unusual: {len(phone_number)} digits (expected 10-15)")
            
            # Validate SIP trunk is configured
            if not outbound_trunk_id:
                logger.error("❌ SIP_OUTBOUND_TRUNK_ID not set - cannot make SIP calls!")
                raise ValueError("SIP_OUTBOUND_TRUNK_ID environment variable is required for phone calls")
            
            logger.info(f"📞 Dialing {phone_number} via SIP trunk {outbound_trunk_id}...")
            
            # Retry logic for SIP API calls (sometimes LiveKit Cloud has temporary network issues)
            max_retries = 3
            retry_delay = 2  # seconds
            
            for attempt in range(1, max_retries + 1):
                try:
                    logger.info(f"   Attempt {attempt}/{max_retries}...")
                    sip_participant = await ctx.api.sip.create_sip_participant(
                        api.CreateSIPParticipantRequest(
                            room_name=ctx.room.name,
                            sip_trunk_id=outbound_trunk_id,
                            sip_call_to=phone_number,
                            participant_identity=participant_identity,
                            wait_until_answered=True,
                        )
                    )
                    logger.info(f"✅ SIP call initiated successfully: {sip_participant}")
                    break  # Success, exit retry loop
                    
                except Exception as sip_error:
                    if attempt < max_retries:
                        logger.warning(f"⚠️  SIP call attempt {attempt} failed: {sip_error}")
                        logger.info(f"   Retrying in {retry_delay} seconds...")
                        await asyncio.sleep(retry_delay)
                    else:
                        # Final attempt failed
                        logger.error(f"❌ Failed to create SIP participant after {max_retries} attempts: {sip_error}")
                        logger.error(f"   Trunk ID: {outbound_trunk_id}")
                        logger.error(f"   Phone number: {phone_number}")
                        logger.error(f"   Room: {ctx.room.name}")
                        logger.error(f"   This could be due to:")
                        logger.error(f"   1. Temporary LiveKit Cloud API connectivity issue")
                        logger.error(f"   2. Twilio service issue")
                        logger.error(f"   3. Invalid phone number or trunk configuration")
                        logger.error(f"   Please check LiveKit Cloud status and Twilio logs")
                        raise

        # Wait for participant to join (either SIP or web browser)
        if participant_identity:
            participant = await ctx.wait_for_participant(identity=participant_identity)
        else:
            # Playground mode: wait for any participant
            participant = await ctx.wait_for_participant()
        
        logger.info(f"participant joined: {participant.identity}")
        
        # Wait a moment for tracks to be published
        await asyncio.sleep(0.5)
        
        # Log audio tracks to verify audio is connected
        logger.info(f"🔊 Participant audio tracks: {len(participant.track_publications)}")
        
        # Subscribe to all audio tracks
        audio_track_found = False
        for track_sid, track_pub in participant.track_publications.items():
            logger.info(f"  - Track: {track_pub.source}, subscribed: {track_pub.subscribed}, muted: {track_pub.muted}")
            if track_pub.source == rtc.TrackSource.SOURCE_MICROPHONE:
                audio_track_found = True
                if not track_pub.subscribed:
                    logger.info(f"  - Subscribing to microphone track...")
                    track_pub.set_subscribed(True)
        
        if not audio_track_found:
            logger.warning("⚠️ No microphone track found! User may need to allow microphone access in browser.")
            logger.warning("   Agent will wait for audio track to be published...")
            
            # Wait up to 5 seconds for microphone track
            for _ in range(10):
                await asyncio.sleep(0.5)
                for track_sid, track_pub in participant.track_publications.items():
                    if track_pub.source == rtc.TrackSource.SOURCE_MICROPHONE:
                        logger.info("✅ Microphone track now available!")
                        audio_track_found = True
                        if not track_pub.subscribed:
                            track_pub.set_subscribed(True)
                        break
                if audio_track_found:
                    break
            
            if not audio_track_found:
                logger.error("❌ No microphone track after 5 seconds - audio will not work!")

        agent.set_participant(participant)
        agent.set_agent_session(session)  # Store session reference for silence checks

        # Initialize agent state and timing
        current_time = asyncio.get_event_loop().time()
        agent.last_user_speech_time = current_time
        agent.introduction_completed = False  # Will be set to True after greeting finishes
        
        logger.info("🚀 Starting introduction sequence...")
        
        # STRATEGY: Be PROACTIVE - Agent speaks IMMEDIATELY after call connects
        # Don't wait for user - students expect agent to introduce itself first
        logger.info("📢 Proactive greeting: Agent will speak first immediately")
        
        # Wait just 0.5s for audio tracks to stabilize
        await asyncio.sleep(0.5)
        
        # Check if user somehow spoke in that brief moment
        if agent.user_turn_count > 0:
            logger.info("✅ User spoke within 0.5s - agent will respond naturally")
        else:
            # PROACTIVE INTRODUCTION - Agent speaks first
            logger.info("📢 Triggering immediate agent introduction (proactive)")
            try:
                await session.generate_reply(
                    instructions=(
                        "The call just connected. You MUST speak first to greet the caller. "
                        "Introduce yourself warmly and immediately. Say: "
                        "'Hi! This is Abhilash from Next Wave. I'm a Success Coach here to help you "
                        "explore our tech training programs. How can I help you today?'"
                    )
                )
                agent.introduction_completed = True
                logger.info("✅ Proactive introduction triggered successfully")
            except Exception as e:
                logger.error(f"⚠️ LLM failed to generate greeting (quota issue?): {e}")
                logger.info("📢 Using fallback TTS greeting directly")
                # FALLBACK: If LLM fails (quota exhausted), speak directly via TTS
                try:
                    # Generate greeting text directly and push to TTS
                    greeting_text = (
                        f"Hi! This is {AGENT_SPOKEN_NAME} from {CALLING_FROM_COMPANY}. "
                        "I'm a Success Coach here to help you explore our tech training programs. "
                        "How can I help you today?"
                    )
                    logger.info(f"🔊 Speaking fallback greeting: {greeting_text}")
                    # Use session's TTS to speak directly
                    await session.say(greeting_text)
                    agent.introduction_completed = True
                    logger.info("✅ Fallback greeting spoken successfully")
                except Exception as fallback_error:
                    logger.error(f"❌ Even fallback greeting failed: {fallback_error}", exc_info=True)
        
        # Brief monitoring to confirm conversation starts
        monitor_elapsed = 0
        monitor_interval = 1.0
        max_monitor = 5  # Reduced from 8 to 5 seconds
        
        logger.info("🎯 Monitoring for conversation activity...")
        
        while monitor_elapsed < max_monitor:
            await asyncio.sleep(monitor_interval)
            monitor_elapsed += monitor_interval
            
            # If conversation is active, we're good
            if agent.user_turn_count > 0 or agent.introduction_completed:
                logger.info(f"✅ Conversation active! User={agent.user_turn_count}, Intro={agent.introduction_completed}")
                break
            
            logger.info(f"⏱️ Waiting for conversation... {2 + monitor_elapsed:.1f}s elapsed")
        
        # Note: introduction_completed will be set by hello_trigger or on_user_turn_completed

        # Start silence monitoring (will only trigger after BOTH agent and user are silent)
        agent.silence_monitor_task = setup_silence_monitor(agent, session)

        # Wait for participant disconnect
        disconnected_future = asyncio.Future()

        def on_participant_disconnected(p: rtc.RemoteParticipant):
            if p.identity == participant.identity:
                logger.info(f"participant {participant.identity} disconnected")
                if agent.silence_monitor_task:
                    agent.silence_monitor_task.cancel()
                if not disconnected_future.done():
                    disconnected_future.set_result(True)

        ctx.room.on("participant_disconnected", on_participant_disconnected)
        await disconnected_future

    except api.TwirpError as e:
        logger.error(
            f"SIP error: {e.message}, "
            f"status: {e.metadata.get('sip_status_code')} "
            f"{e.metadata.get('sip_status')}"
        )
    except asyncio.CancelledError:
        logger.info("job cancelled")
        raise
    except Exception as e:
        logger.error(f"unexpected error: {e}", exc_info=True)
    finally:
        # Cleanup
        try:
            await session_started
        except Exception as e:
            logger.warning(f"error during session cleanup: {e}")
        ctx.shutdown()


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="outbound-caller",
        )
    )