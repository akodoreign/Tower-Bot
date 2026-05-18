#!/usr/bin/env python3
"""Quick script to list available A1111 models."""

import httpx
import json

A1111_URL = "http://127.0.0.1:7860"

def main():
    print("Querying A1111 for available models...\n")
    
    try:
        # Get checkpoints
        resp = httpx.get(f"{A1111_URL}/sdapi/v1/sd-models", timeout=10)
        models = resp.json()
        
        print("=" * 60)
        print("CHECKPOINTS (sd-models)")
        print("=" * 60)
        for m in models:
            title = m.get("title", "?")
            name = m.get("model_name", "?")
            print(f"  • {title}")
        
        # Get current model
        resp = httpx.get(f"{A1111_URL}/sdapi/v1/options", timeout=10)
        opts = resp.json()
        current = opts.get("sd_model_checkpoint", "unknown")
        print(f"\n  ➤ Currently loaded: {current}")
        
        # Get LoRAs
        print("\n" + "=" * 60)
        print("LORAS")
        print("=" * 60)
        try:
            resp = httpx.get(f"{A1111_URL}/sdapi/v1/loras", timeout=10)
            loras = resp.json()
            if loras:
                for lora in loras:
                    name = lora.get("name", "?")
                    print(f"  • {name}")
            else:
                print("  (none found)")
        except Exception as e:
            print(f"  (could not fetch: {e})")
        
        # Get samplers
        print("\n" + "=" * 60)
        print("SAMPLERS")
        print("=" * 60)
        resp = httpx.get(f"{A1111_URL}/sdapi/v1/samplers", timeout=10)
        samplers = resp.json()
        for s in samplers[:10]:  # First 10
            print(f"  • {s.get('name', '?')}")
        if len(samplers) > 10:
            print(f"  ... and {len(samplers) - 10} more")
            
    except httpx.ConnectError:
        print("❌ Could not connect to A1111 at", A1111_URL)
        print("   Make sure Automatic1111 is running with --api flag")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
