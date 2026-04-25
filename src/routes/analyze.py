from fastapi import APIRouter   #define las routas                                                                        
from src.models.conversation import ConversationRequest                                               
from src.controllers.analysis_controller import handle_analyze

router = APIRouter()

@router.post("/analyze")#esta routa solo acepta el metodo post
def analyze(conversation: ConversationRequest):#aqui se leen los datos que mande en el body y los convierte al modelo
      return handle_analyze(conversation) #delega al controller aqui solo son routas
