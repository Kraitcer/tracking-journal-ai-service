"""Main entry point for the Tracking Journal AI service."""
from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response

app = FastAPI()

@app.get("/")
def read_root():
    """Root endpoint returning a simple greeting."""
    return Response(status_code=200, content=JSONResponse(content={"Hello": "World"}).body, media_type="application/json")