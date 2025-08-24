from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from agents import run_property_workflow
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Property Analysis API", version="1.0.0")

# Define the model with street_name and house_number
class AnalyzeReq(BaseModel):
    street_name: str
    house_number: str

@app.post("/analyze")
def analyze(req: AnalyzeReq):
    try:
        # Pass both street_name and house_number separately to the workflow function
        return run_property_workflow(req.street_name, req.house_number)
    except Exception as e:
        logger.exception("analysis failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
def health():
    return {"ok": True}


