"""Local, deterministic civic-request classification and intake prompts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class IntakeAssessment:
    category: str
    summary: str
    details: dict[str, str]
    missing_fields: tuple[str, ...]
    question: str

    @property
    def ready_for_confirmation(self) -> bool:
        return not self.missing_fields


class LocalRequestAssessor:
    _category_keywords = {
        "roads": (
            "pothole", "road", "street", "sidewalk", "footpath", "traffic",
            "சாலை", "தெரு", "பள்ளம்",
        ),
        "water": (
            "water", "pipe", "leak", "drain", "sewage", "குடிநீர்", "தண்ணீர்",
            "குழாய்", "கசிவு", "கழிவுநீர்",
        ),
        "sanitation": (
            "sanitation", "toilet", "public restroom", "sewer", "சுகாதாரம்",
            "கழிப்பறை",
        ),
        "waste": (
            "garbage", "trash", "waste", "rubbish", "குப்பை", "கழிவு",
        ),
        "utilities": (
            "electricity", "power", "streetlight", "street light", "ไฟ",
            "மின்சாரம்", "விளக்கு",
        ),
    }

    def assess(
        self,
        message: str,
        context: Optional[dict[str, Any]] = None,
    ) -> IntakeAssessment:
        text = message.strip()
        if context:
            previous_details = context.get("details", {})
            if not isinstance(previous_details, dict):
                previous_details = {}
            details = {
                "description": str(previous_details.get("description", "")),
                "location": str(previous_details.get("location", "")) or text,
                "urgency": str(previous_details.get("urgency", "")),
            }
            category = context.get("category", "other")
            summary = str(context.get("summary", "")) or text
        else:
            details = {"description": text, "location": "", "urgency": ""}
            category = self._classify(text)
            summary = text[:500]

        missing_fields = tuple(
            field for field in ("description", "location") if not details[field].strip()
        )
        question = (
            "Please provide the location of the issue. / பிரச்சினை உள்ள இடத்தைத் தெரிவிக்கவும்."
            if "location" in missing_fields
            else ""
        )
        return IntakeAssessment(
            category=category,
            summary=summary,
            details=details,
            missing_fields=missing_fields,
            question=question,
        )

    @classmethod
    def _classify(cls, message: str) -> str:
        normalized = message.casefold()
        for category, keywords in cls._category_keywords.items():
            if any(keyword in normalized for keyword in keywords):
                return category
        return "other"
