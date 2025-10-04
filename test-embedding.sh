python app/rag_flow.py \
  --persist_dir ./aha_index \
  --ask "ED low-risk chest pain next steps?" \
  --patient_json '{"age":45,"sex":"female","setting":"ED","ecg":"normal","hs_ctn_0h":3,"hs_ctn_1h":3,"risk_score":{"HEART":2}}'
