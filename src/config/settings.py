from dotenv import load_dotenv                                                                          
import os                                                 

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

#from src.config.settings import GEMINI_API_KEY 
# -De esta forma de se puede llamar a la variable sin hacerla tanta de emocion-