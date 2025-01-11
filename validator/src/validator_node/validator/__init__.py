import asyncio
import threading
import time
import traceback
from collections import deque
from datetime import datetime
from typing import Dict, List

from communex._common import get_node_url
from communex.client import CommuneClient
from communex.compat.key import classic_load_key
from communex.module.module import Module, endpoint
from loguru import logger
from pydantic import BaseModel
from substrateinterface import Keypair

from validator._config import ValidatorSettings
from base import BaseValidator
from base.utils import get_netuid
from validator.validator_ import ValidatorNode


class WeightHistory(BaseModel):
    time: datetime
    data: List


class Validator(BaseValidator, Module):
    def __init__(self, key: Keypair, settings: ValidatorSettings | None = None) -> None:
        super().__init__()
        super(BaseValidator, self).__init__()
        self.settings = settings or ValidatorSettings()
        self.key = key
        
        # Add debug logging for node URL
        node_url = get_node_url(use_testnet=self.settings.use_testnet)
        logger.debug(f"Attempting to connect to node URL: {node_url}")
        
        # Initialize client with detailed error handling
        try:
            logger.debug("Initializing CommuneClient...")
            self._c_client = CommuneClient(node_url)
            logger.debug(f"CommuneClient initialized: {self._c_client}")
            
            # Verify client functionality
            if self._c_client is None:
                raise ValueError("CommuneClient initialization returned None")
                
            # Test client connection
            try:
                logger.debug("Testing subnet query...")
                subnets = self._c_client.query_map_subnet_names()
                logger.debug(f"Available subnets: {subnets}")
            except Exception as e:
                logger.error(f"Failed to query subnets: {e}")
                raise
                
        except Exception as e:
            logger.error(f"Client initialization failed with error: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise

        # Get netuid with additional logging
        try:
            logger.debug("Attempting to get netuid...")
            self.netuid = get_netuid(self._c_client)
            logger.debug(f"Retrieved netuid: {self.netuid}")
        except Exception as e:
            logger.error(f"Failed to get netuid: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise

        # Initialize the ValidatorNode instance
        self.validator_node = ValidatorNode(key=self.key, netuid=self.netuid, client=self._c_client)
        self.weights_histories = deque(maxlen=10)

    @property
    def c_client(self):
        """Communex client for interacting with the network."""
        if not hasattr(self, '_c_client') or self._c_client is None:
            logger.warning("Client accessed but not initialized, attempting to create new client")
            node_url = get_node_url(use_testnet=self.settings.use_testnet)
            self._c_client = CommuneClient(node_url)
        return self._c_client

    async def validate_step(self):
        """Perform a single validation step for all miners."""
        self.validator_node.track_miner_containers()

        # Use miner_data to update weights
        score_dict = self.validator_node.miner_data  # Pre-calculated scores for miners
        logger.debug(f"Score dictionary from miner_data: {score_dict}")

        if not score_dict:
            logger.info("No valid scores, skipping weight update.")
            return

        # Normalize scores
        normalized_scores = self.validator_node.normalize_scores(score_dict)

        # Assign and trim weights
        weighted_scores = {
            miner_uid: self.assign_weight(score)
            for miner_uid, score in normalized_scores.items()
        }
        logger.debug(f"Weighted scores before trimming: {weighted_scores}")

        # Trim to maximum allowed weights
        weighted_scores = self.cut_to_max_allowed_weights(weighted_scores)
        logger.debug(f"Trimmed weights: {weighted_scores}")

        # Submit weights
        if not weighted_scores:
            logger.info("No valid weights to submit after trimming.")
            return

        try:
            uids = list(weighted_scores.keys())
            weights = list(weighted_scores.values())
           
            print(f"uids to reward {uids}")
            print(f"weights to reward {weights}")
            # Update weights history
            weight_data = list(zip(uids, weights))
            self.weights_histories.append(
                WeightHistory(
                    time=datetime.now(),
                    data=weight_data,
                )
            )
            logger.debug(f"Updated weights history: {self.weights_histories}")

            # Submit to network
            logger.info(f"Submitting weights for {len(uids)} miners.")
            self.c_client.vote(
                key=self.key,
                uids=uids,
                weights=weights,
                netuid=self.netuid,
            )

            # self.update_container_payment_status_for_miners(uids)
        except Exception as e:
            logger.error(f"Error submitting weights: {e}")

    def assign_weight(self, score: float) -> int:
        """Scale normalized scores to the network's weight range."""
        max_score = 1.0  # Maximum normalized score
        weight = int(score * 5000 / max_score)  # Scale to 0-5000 range
        return weight

    def cut_to_max_allowed_weights(self, score_dict: Dict[int, float], max_allowed_weights: int = 420) -> Dict[int, float]:
        """Trim weights to the maximum allowed count."""
        if len(score_dict) > max_allowed_weights:
            sorted_scores = sorted(score_dict.items(), key=lambda x: x[1], reverse=True)
            trimmed = dict(sorted_scores[:max_allowed_weights])
            logger.info(f"Trimmed scores to max allowed: {trimmed}")
            return trimmed
        return score_dict
    
    def update_container_payment_status_for_miners(self, uids: List[str]):
        """
        Update the payment status of containers for miners after weights are set.

        Args:
            uids (List[str]): List of miner UIDs whose weights have been updated.
        """
        try:
            for miner_uid in uids:
                # Retrieve containers associated with the miner
                containers = self.validator_node.get_containers_for_miner(miner_uid)
                for container in containers:
                    if container.get('payment_status') == 'pending':
                        success = self.validator_node.update_container_payment_status(container['id'])
                        if success:
                            logger.info(f"Payment status updated for container {container['id']} (miner {miner_uid})")
                        else:
                            logger.warning(f"Failed to update payment status for container {container['id']} (miner {miner_uid})")
        except Exception as e:
            logger.error(f"Error while updating container payment statuses: {e}")

    def validation_loop(self):
        """Continuously validate miners."""
        while True:
            try:
                asyncio.run(self.validate_step())
                time.sleep(self.settings.iteration_interval)
            except Exception as e:
                logger.error(f"Error in validation loop: {e}")
                logger.error(traceback.format_exc())

    def start_validation_loop(self):
        """Start the validation loop in a separate thread."""
        logger.info("Starting validation loop...")
        thread = threading.Thread(target=self.validation_loop, daemon=True)
        thread.start()

    @endpoint
    def get_weights_history(self):
        """Retrieve the history of weights."""
        return list(self.weights_histories)

    def serve(self):
        """Serve the validator."""
        import uvicorn
        from communex.module.server import ModuleServer

        self.start_validation_loop()
        if self.settings.port:
            logger.info("Server enabled")
            server = ModuleServer(self, self.key, subnets_whitelist=[self.netuid])
            app = server.get_fastapi_app()
            uvicorn.run(app, host=self.settings.host, port=self.settings.port)
        else:
            while True:
                time.sleep(60)


if __name__ == "__main__":
    settings = ValidatorSettings(use_testnet=True)
    Validator(key=classic_load_key("validator-key"), settings=settings).serve()
