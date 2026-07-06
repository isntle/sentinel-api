import sys
import os
import json
import uuid
import time
from sqlalchemy.orm import Session
from groq import Groq

# Ensure src modules can be imported
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import get_db
from src.models.db_models import Feedback, HotTerm, RejectedTerm
from src.config.settings import GROQ_API_KEY
from src.routes.feedback import get_feedback_stats

# Criteria for auto-calibration
MIN_REPORTS = 5
MIN_FP_RATE = 40.0 # 40%

def auto_calibrate():
    print("Starting Auto-Calibration Process...")
    gen = get_db()
    db: Session = next(gen)

    # No podemos llamar get_feedback_stats directamente porque devuelve JSONResponse,
    # así que replicamos la lógica de stats aquí.
    all_feedback = db.query(Feedback).all()
    term_stats = {}
    
    for f in all_feedback:
        try:
            verdict = json.loads(f.verdict_original)
            terms = verdict.get('terms', [])
            if not terms and 'layers' in verdict:
                layers = verdict['layers']
                if 'v3_matches' in layers:
                    terms = [m.get('term') for m in layers['v3_matches']]
            
            for term in terms:
                if not term:
                    continue
                if term not in term_stats:
                    term_stats[term] = {"total_reports": 0, "false_positives": 0, "contexts": []}
                
                term_stats[term]["total_reports"] += 1
                if f.feedback_type == "false_positive":
                    term_stats[term]["false_positives"] += 1
                    # Store context if available in comment
                    if f.comment:
                        term_stats[term]["contexts"].append(f.comment)
        except Exception:
            continue
            
    # Filter terms that meet the criteria
    problematic_terms = []
    for term, stats in term_stats.items():
        fp_rate = (stats["false_positives"] / stats["total_reports"]) * 100 if stats["total_reports"] > 0 else 0
        if stats["total_reports"] >= MIN_REPORTS and fp_rate >= MIN_FP_RATE:
            problematic_terms.append({
                "term": term,
                "total_reports": stats["total_reports"],
                "false_positives": stats["false_positives"],
                "fp_rate": fp_rate,
                "contexts": stats["contexts"][:10] # limit to 10 contexts for prompt
            })
            
    if not problematic_terms:
        print("No problematic terms found. Calibration not needed.")
        return

    print(f"Found {len(problematic_terms)} problematic terms. Consulting Groq...")
    client = Groq(api_key=GROQ_API_KEY)
    
    for item in problematic_terms:
        term = item["term"]
        contexts_str = "\n".join([f"- {ctx}" for ctx in item["contexts"]]) if item["contexts"] else "Sin contexto específico reportado."
        
        prompt = f"""
Eres el evaluador de calidad del motor de detección Sentinel (seguridad infantil).
Hemos recibido múltiples reportes de "Falso Positivo" para el término: "{term}".

Estadísticas:
- Reportes totales: {item['total_reports']}
- Falsos positivos: {item['false_positives']} (Tasa: {item['fp_rate']:.1f}%)

Contextos reportados donde falló:
{contexts_str}

Tu tarea es evaluar si este término es demasiado polisémico (tiene muchos significados normales benignos) o si está generando demasiado ruido.
Responde SOLO con un JSON con la siguiente estructura:
{{
  "action": "reduce_weight" | "deactivate" | "keep",
  "recommended_weight": <nuevo peso sugerido si la accion es reduce_weight, ej. 2.0>,
  "reasoning": "Explicación breve de la decisión"
}}
Si el término es claramente peligroso pero falló por falta de contexto, sugiere reduce_weight.
Si el término es muy común (ej. "hola", "escuela", "jugar") sugiere deactivate.
"""
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            
            result = json.loads(response.choices[0].message.content)
            action = result.get("action")
            reasoning = result.get("reasoning")
            
            print(f"Term: {term} -> Action: {action} ({reasoning})")
            
            # Apply changes to DB
            hot_term = db.query(HotTerm).filter(HotTerm.term == term).first()
            if not hot_term:
                print(f"Term '{term}' not found in DB. Skipping.")
                continue
                
            if action == "deactivate":
                print(f"Deactivating term '{term}' (Moving to staged for removal review)")
                # We move it to staged so human can review the deletion
                hot_term.approved = False
                hot_term.staged = True
                db.commit()
            elif action == "reduce_weight":
                new_weight = float(result.get("recommended_weight", hot_term.weight / 2))
                print(f"Reducing weight of term '{term}' from {hot_term.weight} to {new_weight}")
                hot_term.weight = new_weight
                db.commit()
            else:
                print(f"Keeping term '{term}' as is.")
                
        except Exception as e:
            print(f"Error evaluating term '{term}': {e}")
            
    print("Auto-Calibration Completed.")
    
    # Clean up DB session
    try:
        next(gen)
    except StopIteration:
        pass

if __name__ == "__main__":
    auto_calibrate()
