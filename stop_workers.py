"""
Stop all running LiveKit workers
"""
import asyncio
import os
from dotenv import load_dotenv
from livekit import api

load_dotenv(dotenv_path=".env.local")

async def stop_all_workers():
    """Stop all running workers in the LiveKit project"""
    
    # Get credentials from environment
    livekit_url = os.getenv("LIVEKIT_URL")
    livekit_api_key = os.getenv("LIVEKIT_API_KEY")
    livekit_api_secret = os.getenv("LIVEKIT_API_SECRET")
    
    print(f"🔍 Connecting to LiveKit: {livekit_url}")
    
    # Create LiveKit API client
    lk_api = api.LiveKitAPI(
        url=livekit_url,
        api_key=livekit_api_key,
        api_secret=livekit_api_secret,
    )
    
    try:
        # List all active rooms
        print("\n📋 Checking for active rooms...")
        rooms = await lk_api.room.list_rooms(api.ListRoomsRequest())
        
        if not rooms or len(rooms.rooms) == 0:
            print("✅ No active rooms found")
        else:
            print(f"Found {len(rooms.rooms)} active room(s):")
            for room in rooms.rooms:
                print(f"\n  Room: {room.name}")
                print(f"  - Participants: {room.num_participants}")
                print(f"  - Created: {room.creation_time}")
                
                # Delete the room (this will disconnect all participants and workers)
                print(f"  🗑️  Deleting room '{room.name}'...")
                await lk_api.room.delete_room(api.DeleteRoomRequest(room=room.name))
                print(f"  ✅ Room '{room.name}' deleted")
        
        print("\n✅ All workers and rooms cleaned up!")
        print("\nYou can now start a fresh agent with:")
        print("  .\\venv\\Scripts\\python.exe agent.py start")
    
    except Exception as e:
        print(f"❌ Error: {e}")
    
    finally:
        await lk_api.aclose()

if __name__ == "__main__":
    asyncio.run(stop_all_workers())
