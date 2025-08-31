# -*- coding: utf-8 -*-
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from agents import run_property_workflow
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Property Analysis API", version="1.1.0")

class AnalyzeReq(BaseModel):
    street_name: str
    house_number: str
    user_questions: Optional[List[str]] = None

@app.post("/analyze")
def analyze(req: AnalyzeReq):
    try:
        return run_property_workflow(req.street_name, req.house_number, req.user_questions)
    except Exception as e:
        logger.exception("analysis failed")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health():
    return {"ok": True}
