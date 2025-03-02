from typing import List

from base.config import PolarisBaseSettings


class ValidatorSettings(PolarisBaseSettings):
    call_timeout: int = 60
    host: str = "0.0.0.0"
    port: int = 8000
    iteration_interval: int = 800
    max_allowed_weights: int=500
    subnet_name: str ="compute"
    logging_level: str ="INFO"
