import time
import json
import os
from datetime import datetime, timezone
import dspy
from dspy.clients.lm import LM

# Default limits for Gemini Free Tier
DEFAULT_LIMITS = {
    "RPM": 5,           # Requests per minute
    "RPD": 20,          # Requests per day
    "MIN_INTERVAL": 60.0 / 5  # Seconds between requests
}

USAGE_FILE = "key_usage.json"

class SmartMultiKeyLM(LM):
    def __init__(self, model, api_keys, limits=None, **kwargs):
        """
        Args:
            model (str): The model name (e.g., "gemini/gemini-1.5-flash")
            api_keys (list): List of API key strings.
            limits (dict): Optional override for limits (RPM, RPD).
            **kwargs: Extra args for dspy.LM (temperature, max_tokens, etc.)
        """
        # Initialize parent with first key for default setup
        super().__init__(model, api_key=api_keys[0], **kwargs)
        
        self.api_keys = api_keys
        self.clients = {}
        
        # Apply custom limits or defaults
        self.limits = limits if limits else DEFAULT_LIMITS
        # Recalculate interval in case RPM changed
        self.limits["MIN_INTERVAL"] = 60.0 / self.limits["RPM"]

        # Map keys to simple IDs (Key #1, Key #2) for cleaner logging
        self.key_ids = {k: i+1 for i, k in enumerate(api_keys)}
        
        # Initialize sub-clients
        for key in api_keys:
            self.clients[key] = dspy.LM(model, api_key=key, **kwargs)
            
        self.usage_data = self._load_usage()

    def _load_usage(self):
        """Loads usage data from disk."""
        if os.path.exists(USAGE_FILE):
            try:
                with open(USAGE_FILE, "r") as f:
                    data = json.load(f)
                
                # Reset if new day (UTC)
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                if data.get("date") != today:
                    print(f"[System] New day detected ({today}). Resetting quotas.")
                    return {"date": today, "keys": {k: {"daily_reqs": 0, "last_used": 0} for k in self.api_keys}}
                
                # Ensure keys exist
                for k in self.api_keys:
                    if k not in data["keys"]:
                        data["keys"][k] = {"daily_reqs": 0, "last_used": 0}
                return data
            except Exception:
                pass # If file is corrupt, start fresh
        
        return {
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "keys": {k: {"daily_reqs": 0, "last_used": 0} for k in self.api_keys}
        }

    def _save_usage(self):
        with open(USAGE_FILE, "w") as f:
            json.dump(self.usage_data, f, indent=2)

    def _get_available_key(self):
        now = time.time()
        
        # 1. Try to find an immediately ready key
        for key in self.api_keys:
            stats = self.usage_data["keys"][key]
            
            if stats["daily_reqs"] >= self.limits["RPD"]:
                continue 
            
            if (now - stats["last_used"]) >= self.limits["MIN_INTERVAL"]:
                return key, 0

        # 2. If all busy, find the one with shortest wait
        best_key = None
        min_wait = float('inf')
        
        for key in self.api_keys:
            stats = self.usage_data["keys"][key]
            if stats["daily_reqs"] >= self.limits["RPD"]:
                continue
            
            wait = self.limits["MIN_INTERVAL"] - (now - stats["last_used"])
            if wait < min_wait:
                min_wait = wait
                best_key = key
        
        return best_key, max(0, min_wait)

    def __call__(self, prompt=None, messages=None, **kwargs):
        key, wait_time = self._get_available_key()
        
        if key is None:
            raise Exception("CRITICAL: All API keys have reached their Daily Limit.")
        
        key_id = self.key_ids[key]

        if wait_time > 0:
            print(f"  [Throttling] All keys busy. Key #{key_id} ready in {wait_time:.1f}s...")
            time.sleep(wait_time)

        client = self.clients[key]
        
        try:
            current_count = self.usage_data["keys"][key]["daily_reqs"] + 1
            print(f"Requesting... (Key #{key_id} | Today: {current_count}/{self.limits['RPD']})")
            
            response = client(prompt=prompt, messages=messages, **kwargs)
            
            self.usage_data["keys"][key]["daily_reqs"] += 1
            self.usage_data["keys"][key]["last_used"] = time.time()
            self._save_usage()
            
            self.history.append(client.history[-1])
            return response

        except Exception as e:
            error_msg = str(e).lower()
            if any(x in error_msg for x in ["429", "quota", "resource_exhausted"]):
                print(f"!! Key #{key_id} hit unexpected limit. Switching...")
                # Reset timer to force switch
                self.usage_data["keys"][key]["last_used"] = time.time() 
                self._save_usage()
                return self.__call__(prompt, messages, **kwargs)
            else:
                raise e

# --- Helper Function for Easy Import ---
def get_gemini_manager(api_keys, model="gemini/gemini-1.5-flash", rpm=5, rpd=1000):
    """
    Factory function to quickly get a configured DSPy manager.
    """
    custom_limits = {
        "RPM": rpm,
        "RPD": rpd,
        "MIN_INTERVAL": 60.0 / rpm
    }
    return SmartMultiKeyLM(model, api_keys, limits=custom_limits)

# --- Append this to the bottom of multikey_manager.py ---

if __name__ == "__main__":
    print("--- Running Smart Gemini Manager Test ---")
    
    # 1. Setup Dummy Keys for testing (replace with real keys to actually test connection)
    test_keys = [
 
        "AIzaSyDiY7Otu_q9J_27wNfl7ysg_RU4UUOy_5Q",
        "AIzaSyBqR25716ps7gxjXFxHzDYGv0zTItHkTUY",
        "AIzaSyCElp7OZU1-aRLpYDmqnJnbDuyd-FKF_iY",
        "AIzaSyDOk6R1r6FKRHVxkTSy5cMIIW1j4mmxoZ4",# conny
        "AIzaSyAgOXEjxsSNFsKsY8KbPBPsmSMavTtCjpQ"
    ]
  
    
    # 2. Initialize the Manager
    # We use a very strict RPM (limit) to force it to switch keys immediately for demonstration
    print(f"Initializing with {len(test_keys)} keys...")
    lm = get_gemini_manager(test_keys, model="gemini/gemini-3-flash-preview", rpm=60, rpd=5)
    dspy.configure(lm=lm)
    
    # 3. Run a quick loop
    print("\n[Test] Sending 3 rapid requests to trigger logic:")
    
    try:
        # We use a simple loop. Since these keys are likely fake, this will fail 
        # on the actual network request, but you will see the LOGS showing key rotation.
        for i in range(1, 4):
            print(f"\n--- Request {i} ---")
            # We wrap in try/except because fake keys will raise 400/403 errors
            try:
                # Simple pass-through test
                dspy.ChainOfThought("question -> answer")(question=f"Test Q{i}")
            except Exception as e:
                # We expect this to fail if keys are fake, but check the CONSOLE output
                print(f"(Expected Error with fake keys): {e}")
                
    except KeyboardInterrupt:
        print("\nTest stopped by user.")
    
    print("\nDone. Check 'key_usage.json' to see persistent stats.")
# EXMAPLE

# import dspy
# from multikey_manager import get_gemini_manager

# # 1. Setup Keys
# my_keys = [
#     "AIzaSyD-KEY1...",
#     "AIzaSyD-KEY2...",
# ]

# # 2. Get the Manager
# # You can customize RPM (speed) and RPD (daily limit) here
# lm = get_gemini_manager(my_keys, model="gemini/gemini-3-flash-preview", rpm=5, rpd=1500)

# # 3. Configure DSPy
# dspy.configure(lm=lm)

# # 4. Run your code
# print(dspy.ChainOfThought("question -> answer")(question="Hello"))