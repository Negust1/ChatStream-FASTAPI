from fastapi import FastAPI

# This variable MUST be named "app" to match your command
app = FastAPI(title="Chatbot API")

@app.get("/")
def read_root():
    return {"message": "Hello App"}


