import requests

def call_model(prompt: str):
    url = "https://api-be.dev.simpplr.xyz/v1/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "x-smtip-tid": "219a9c8b-3baf-47ca-8337-3901b08695d1",
        "x-smtip-feature": "smart_answers"
    }

    payload = {
        "model": "auto-route",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 100
    }

    try:
        # We use the json parameter to automatically serialize the dictionary and set the content-type
        response = requests.post(url, headers=headers, json=payload)
        
        # Raise an exception for bad status codes (4xx or 5xx)
        response.raise_for_status()
        
        # Return the parsed JSON response
        return response.json()
        
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        if response is not None:
            print(f"Response text: {response.text}")
        return None

# Example usage
if __name__ == "__main__":
    user_prompt = "Say hello in two words"
    result = call_model(user_prompt)
    
    if result:
        print(" Response:")
        print(result["choices"][0]["message"]["content"])