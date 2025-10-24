from __future__ import annotations

import asyncio
import logging
from dotenv import load_dotenv
import json
import os
from typing import Any

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
from livekit.plugins import google, noise_cancellation
from livekit.plugins.turn_detector.english import EnglishModel
from livekit.agents import ChatContext, ChatMessage


# load environment variables, this is optional, only used for local development
load_dotenv(dotenv_path=".env.local")
logger = logging.getLogger("outbound-caller")
logger.setLevel(logging.INFO)

outbound_trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID")

# Success Coach Configuration
AGENT_SPOKEN_NAME = "Kushal"
CALLING_FROM_COMPANY = "Next Wave"
AGENT_ROLE = "AI Success Coach"
PRIMARY_WEBSITE_CTA = "ccbp.in"
PRIMARY_PHONE_CTA = "+91-8978487795"


def get_success_coach_instructions():
    """Simple Success Coach AI agent instructions"""
    return f"""You are {AGENT_SPOKEN_NAME}, an AI Success Coach from {CALLING_FROM_COMPANY}. 

IMPORTANT: You must speak ONLY in English language.

BEHAVIOR INSTRUCTIONS:
1. Always start by introducing yourself when you connect to a new call
2. After introduction, wait for the student to ask questions
3. You can answer basic questions about the Nxtwave Edtech company and its different products and services
4. Be warm, supportive, and encouraging
5. Keep responses simple and helpful
6. If you don't know something, politely direct them to contact a human success coach

CONTACT INFORMATION:
- Website: {PRIMARY_WEBSITE_CTA}
- Phone: {PRIMARY_PHONE_CTA}

Remember: Speak only in English. Introduce yourself first"""


class SuccessCoachAgent(Agent):
    def __init__(self, llm_instructions) -> None:
        super().__init__(instructions=llm_instructions)
        # keep reference to the participant for transfers
        self.participant: rtc.RemoteParticipant | None = None
        self.dial_info: dict[str, Any] = {}

    def set_participant(self, participant: rtc.RemoteParticipant):
        self.participant = participant
        
    def set_dial_info(self, dial_info: dict[str, Any]):
        self.dial_info = dial_info

    async def on_user_turn_completed(
        self, turn_ctx: ChatContext, new_message: ChatMessage,
    ) -> None:
        user_query = new_message.text_content()
        print(f"Student says: {user_query}")
        # Log the interaction for success coach dashboard
        print(f"[SUCCESS COACH LOG] Student query: {user_query}")

    async def hangup(self):
        """Helper function to hang up the call by deleting the room"""

        job_ctx = get_job_context()
        await job_ctx.api.room.delete_room(
            api.DeleteRoomRequest(
                room=job_ctx.room.name,
            )
        )

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
        """Called when the user wants to end the call"""
        logger.info(f"ending the call for {self.participant.identity}")

        # let the agent finish speaking
        current_speech = ctx.session.current_speech
        if current_speech:
            await current_speech.wait_for_playout()

        await self.hangup()

    @function_tool()
    async def detected_answering_machine(self, ctx: RunContext):
        """Called when the call reaches voicemail. Use this tool AFTER you hear the voicemail greeting"""
        logger.info(f"detected answering machine for {self.participant.identity}")
        await self.hangup()


async def entrypoint(ctx: JobContext):
    logger.info(f"connecting to room {ctx.room.name}")
    await ctx.connect()

    # when dispatching the agent, we'll pass it the approriate info to dial the user
    # dial_info is a dict with the following keys:
    # - phone_number: the phone number to dial
    # - transfer_to: the phone number to transfer the call to when requested
    try:
        dial_info = json.loads(ctx.job.metadata) if ctx.job.metadata else {}
    except json.JSONDecodeError:
        logger.warning("Invalid or empty JSON metadata, using default dial_info")
        dial_info = {}
    
    # Provide default values for console/testing mode
    phone_number = dial_info.get("phone_number", "+916301165855")  # Default test number
    participant_identity = phone_number
    
    # Ensure transfer_to exists in dial_info for the transfer_call function
    if "transfer_to" not in dial_info:
        dial_info["transfer_to"] = "+13157918654"  # Default transfer number

    # Get Success Coach instructions
    llm_instructions = get_success_coach_instructions()
    
    # Create Success Coach agent
    agent = SuccessCoachAgent(llm_instructions=llm_instructions)
    agent.set_dial_info(dial_info)

    # Using Google Realtime model for Success Coach
    session = AgentSession(
        llm=google.beta.realtime.RealtimeModel(
            model="gemini-2.0-flash-exp",
            voice="Puck",
            temperature=0.7,
            instructions=llm_instructions,
        ),
    )

    # start the session first before dialing, to ensure that when the user picks up
    # the agent does not miss anything the user says
    session_started = asyncio.create_task(
        session.start(
            agent=agent,
            room=ctx.room,
            room_input_options=RoomInputOptions(
                # enable Krisp background voice and noise removal
                noise_cancellation=noise_cancellation.BVC(),
            ),
        )
    )

    # `create_sip_participant` starts dialing the user
    try:
        await ctx.api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=ctx.room.name,
                sip_trunk_id=outbound_trunk_id,
                sip_call_to=phone_number,
                participant_identity=participant_identity,
                # function blocks until user answers the call, or if the call fails
                wait_until_answered=True,
            )
        )

        # wait for the agent session start and participant join
        await session_started
        participant = await ctx.wait_for_participant(identity=participant_identity)
        logger.info(f"participant joined: {participant.identity}")

        agent.set_participant(participant)

    except api.TwirpError as e:
        logger.error(
            f"error creating SIP participant: {e.message}, "
            f"SIP status: {e.metadata.get('sip_status_code')} "
            f"{e.metadata.get('sip_status')}"
        )
        ctx.shutdown()


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="outbound-caller",
        )
    )
    