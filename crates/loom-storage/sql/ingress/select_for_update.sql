SELECT record
FROM loom_ingress
WHERE ingress_id = $1
FOR UPDATE;

