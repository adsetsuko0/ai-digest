from fastapi import FastAPI

app = FastAPI(
    title='AI Digest',
    description='Personal feed AI digest',
    version='0.1.0'
)

@app.get('/')
def root():
    return{'message': 'Welcome to AI Digest!'}

@app.get('/health')
def health():
    return {'status': 'ok'}



