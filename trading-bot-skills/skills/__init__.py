"""
Skills Package
Modular trading bot skills for algorithmic trading.
"""
from skills.base_skill import Skill, Context, SkillExecutionError, SkillConfigError

__all__ = [
    'Skill',
    'Context', 
    'SkillExecutionError',
    'SkillConfigError'
]

__version__ = '0.1.0'
