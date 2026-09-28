"""Concrete contracts for isolated unit assertions, never process registration."""

from wrs_agent.schemas import FeatureSnapshot
from wrs_agent.skills.robot import SKILLS as ROBOT_SKILLS
from wrs_agent.skills.speech import SKILLS as SPEECH_SKILLS

SKILLS = {**ROBOT_SKILLS, **SPEECH_SKILLS}
BINDINGS = {**dict.fromkeys(ROBOT_SKILLS, "wrs"), "speak": "tts"}


def features(names, **values):
    versions = (
        names if isinstance(names, dict) and all(type(v) is int for v in names.values())
        else {n: SKILLS[n].version for n in names}
    )
    return FeatureSnapshot(
        skills=versions,
        specs={n: SKILLS[n].spec for n in versions},
        **values,
    )


def all_features():
    return {"wrs": features(ROBOT_SKILLS), "tts": features(SPEECH_SKILLS)}
