from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
import sys
from io import StringIO
import traceback
import re
import os

# Gemini
from google import genai
from google.genai import types

app = FastAPI()

# ---------------- CORS ----------------
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- Request Model ----------------
class CodeRequest(BaseModel):
    code: str


# ---------------- Tool Function ----------------
def execute_python_code(code: str) -> dict:
    """
    Executes Python code and returns exact stdout or traceback.
    """
    old_stdout = sys.stdout
    sys.stdout = StringIO()

    try:
        exec(code)
        output = sys.stdout.getvalue()
        return {"success": True, "output": output}

    except Exception:
        output = traceback.format_exc()
        return {"success": False, "output": output}

    finally:
        sys.stdout = old_stdout


# ---------------- AI Schema ----------------
class ErrorAnalysis(BaseModel):
    error_lines: List[int]


# ---------------- Fallback parser ----------------
def extract_line_numbers_from_traceback(tb: str) -> List[int]:
    """
    Extract only user-code line numbers from traceback.
    Filters out internal framework lines.
    """
    matches = re.findall(r'File "<string>", line (\d+)', tb)
    lines = sorted(set(int(x) for x in matches))
    return lines


# ---------------- AI Analyzer ----------------
def analyze_error_with_ai(code: str, tb: str) -> List[int]:
    """
    Uses Gemini only when needed.
    Falls back safely if AI fails.
    """
    try:
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

        prompt = f"""
Analyze Python code and its traceback.
Return ONLY the line number(s) where the error occurs.

CODE:
{code}

TRACEBACK:
{tb}
"""

        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "error_lines": types.Schema(
                            type=types.Type.ARRAY,
                            items=types.Schema(type=types.Type.INTEGER),
                        )
                    },
                    required=["error_lines"],
                ),
            ),
        )

        parsed = ErrorAnalysis.model_validate_json(response.text)

        # clean + validate AI output
        lines = sorted(set(parsed.error_lines))
        return lines if lines else extract_line_numbers_from_traceback(tb)

    except Exception:
        return extract_line_numbers_from_traceback(tb)


# ---------------- Endpoint ----------------
@app.post("/code-interpreter")
def run_code(req: CodeRequest):

    execution = execute_python_code(req.code)

    # SUCCESS
    if execution["success"]:
        return {
            "error": [],
            "result": execution["output"]
        }

    # ERROR → analyze
    error_lines = analyze_error_with_ai(req.code, execution["output"])

    return {
        "error": error_lines,
        "result": execution["output"]
    }