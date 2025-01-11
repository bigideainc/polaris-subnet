import os
import sys
from dataclasses import dataclass
from typing import Annotated, Optional
import typer
from communex.compat.key import classic_load_key
from loguru import logger
from validator import Validator, ValidatorSettings

cli = typer.Typer()

@dataclass
class ExtraCtxData:
    use_testnet: bool


@cli.callback()
def main(
    ctx: typer.Context,
    testnet: Annotated[
        bool, typer.Option(envvar="COMX_USE_TESTNET", help="Use testnet endpoints.")
    ] = False,
    log_level: str = "INFO",
):
    logger.remove()
    logger.add(sys.stdout, level=log_level.upper())

    if testnet:
        logger.info("use testnet")
    else:
        logger.info("use mainnet")

    ctx.obj = ExtraCtxData(use_testnet=testnet)


@cli.command("validator")
def validator(
    ctx: typer.Context,
    commune_key: Annotated[
        str, typer.Argument(help="Name of the key present in `~/.commune/key`")
    ],
    host: Annotated[
        Optional[str],
        typer.Argument(
            help="the public ip you've registered, you can simply put 0.0.0.0 here to allow all incoming requests"
        ),
    ] = "0.0.0.0",
    port: Annotated[Optional[int], typer.Argument(help="port")] = 0,
    call_timeout: int = 30,
    iteration_interval: int = 60,
):
    
    settings = ValidatorSettings(
        use_testnet=ctx.obj.use_testnet,
        iteration_interval=iteration_interval,
        call_timeout=call_timeout,
        host=host,
        port=port,
        max_allowed_weights=500,
        subnet_name='compute',
        logging_level='INFO'
    )
    validator = Validator(key=classic_load_key(commune_key), settings=settings)
    validator.serve()

if __name__ == "__main__":
    cli()
