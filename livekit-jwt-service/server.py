"""
LiveKit JWT Service
Validates Matrix access tokens and issues LiveKit tokens for VoIP sessions.
"""

import os
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx
from livekit import api

app = FastAPI()

# Configuration from environment
LIVEKIT_API_KEY = os.environ.get("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.environ.get("LIVEKIT_API_SECRET")
SYNAPSE_URL = os.environ.get("SYNAPSE_URL", "http://synapse:8008")

class TokenRequest(BaseModel):
    matrix_token: str
    room_alias: str


async def resolve_room_id(
    client: httpx.AsyncClient, matrix_token: str, room_alias: str
) -> str:
    """Resolve a Matrix room alias to a room ID, or pass through room IDs."""
    if room_alias.startswith("!"):
        return room_alias

    resp = await client.get(
        f"{SYNAPSE_URL}/_matrix/client/v3/directory/room/{quote(room_alias, safe='')}",
        headers={"Authorization": f"Bearer {matrix_token}"},
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=403, detail="Unknown or inaccessible Matrix room")

    room_data = resp.json()
    room_id = room_data.get("room_id")
    if not room_id:
        raise HTTPException(status_code=403, detail="Failed to resolve Matrix room")

    return room_id


async def require_room_membership(
    client: httpx.AsyncClient, matrix_token: str, room_id: str
) -> None:
    """Ensure the requesting user is already joined to the target room."""
    resp = await client.get(
        f"{SYNAPSE_URL}/_matrix/client/v3/joined_rooms",
        headers={"Authorization": f"Bearer {matrix_token}"},
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=403, detail="Unable to verify Matrix room membership")

    joined_rooms = resp.json().get("joined_rooms", [])
    if room_id not in joined_rooms:
        raise HTTPException(status_code=403, detail="User is not joined to the requested room")

@app.post("/token")
async def get_token(request: TokenRequest):
    """
    Validates the Matrix token with Synapse and returns a LiveKit JWT.
    """
    # 1. Validate with Synapse
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                f"{SYNAPSE_URL}/_matrix/client/v3/account/whoami",
                headers={"Authorization": f"Bearer {request.matrix_token}"}
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid Matrix token")
            
            user_data = resp.json()
            user_id = user_data["user_id"]
            room_id = await resolve_room_id(client, request.matrix_token, request.room_alias)
            await require_room_membership(client, request.matrix_token, room_id)
            
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="Synapse unavailable")

    # 2. Generate LiveKit Token
    token = api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
    
    # Configure grant
    grant = api.VideoGrants(
        room_join=True,
        room=request.room_alias,
        can_publish=True,
        can_subscribe=True,
    )
    
    token.identity = user_id
    token.name = user_id.split(":")[0].replace("@", "")
    token.metadata = ""
    token.add_grant(grant)

    return {"token": token.to_jwt()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
