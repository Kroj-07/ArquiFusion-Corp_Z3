import json
import os


class GeminiAssistant:
    def __init__(self, project, location, model):
        from google import genai
        self.client = genai.Client(
            vertexai=True,
            project=project,
            location=location,
        )
        self.model = model

    def explain(self, alert, role):
        context = {
            "alert": alert,
            "role": role,
            "instruction": (
                "Explica en español esta alerta para el rol indicado. Usa solo los datos "
                "proporcionados; no infieras hechos ni recomiendes acciones fuera de "
                "recommended_action. Si falta evidencia, dilo explícitamente."
            ),
        }
        response = self.client.models.generate_content(
            model=self.model,
            contents=json.dumps(context, ensure_ascii=False, default=str),
        )
        text = (response.text or "").strip()
        if not text:
            raise RuntimeError("Gemini returned an empty explanation")
        return text

    def ask(self, question, role, sources):
        response = self.client.models.generate_content(
            model=self.model,
            contents=json.dumps({
                "question": question,
                "role": role,
                "sources": sources,
                "instruction": (
                    "Responde en español solo con la información de sources. "
                    "Si no alcanza, di que no hay evidencia suficiente y cita los IDs "
                    "de máquina/alerta utilizados."
                ),
            }, ensure_ascii=False, default=str),
        )
        text = (response.text or "").strip()
        if not text:
            raise RuntimeError("Gemini returned an empty answer")
        return text

    @classmethod
    def from_environment(cls):
        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        if not project:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT must be configured")
        return cls(
            project,
            os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
            os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
        )
