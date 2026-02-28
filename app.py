from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
import sys
from io import StringIO
import traceback
import re
import os

from openai import OpenAI

app = FastAPI()

# ---------- CORS ----------
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- OpenAI Client ----------
client = OpenAI(api_key="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")

# ---------- Request Model ----------
class CodeRequest(BaseModel):
    code: str


# ---------- Tool Function ----------
def execute_python_code(code: str) -> dict:
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


# ---------- Fallback parser ----------
def extract_line_numbers(tb: str) -> List[int]:
    matches = re.findall(r'File "<string>", line (\d+)', tb)
    return sorted(set(int(x) for x in matches))


# ---------- AI Analyzer ----------
def analyze_error_with_ai(code: str, tb: str) -> List[int]:
    try:
        prompt = f"""
Identify the line number(s) where the error occurred.

CODE:
{code}

TRACEBACK:
{tb}
"""

        response = client.responses.create(
            model="gpt-4.1-mini",
            input=prompt,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "error_schema",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "error_lines": {
                                "type": "array",
                                "items": {"type": "integer"}
                            }
                        },
                        "required": ["error_lines"]
                    }
                }
            }
        )

        data = response.output_parsed
        lines = sorted(set(data["error_lines"]))
        return lines if lines else extract_line_numbers(tb)

    except Exception:
        return extract_line_numbers(tb)


# ---------- Endpoint ----------
@app.post("/code-interpreter")
def run_code(req: CodeRequest):

    execution = execute_python_code(req.code)

    # SUCCESS
    if execution["success"]:
        return {
            "error": [],
            "result": execution["output"]
        }

    # ERROR → AI analyze
    error_lines = analyze_error_with_ai(req.code, execution["output"])

    return {
        "error": error_lines,
        "result": execution["output"]
    }
