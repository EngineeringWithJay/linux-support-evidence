# The intended contract is app on 8081; a bad config duplicates incumbent's 8080.
start_child incumbent python3 /lab/scenarios/tcp_service.py incumbent 8080
incumbent=$child
wait_ready "$incumbent" incumbent
printf 'PORT=8080\n' > /tmp/app.env
expect 0 config-before cat /tmp/app.env
source /tmp/app.env
expect 78 app-failed python3 /lab/scenarios/tcp_service.py app "$PORT"
expect 0 ss-before ss -ltnp '( sport = :8080 or sport = :8081 )'
expect 2 connect-before python3 /lab/tools/probe.py 8081 app
expect 0 incumbent-before python3 /lab/tools/probe.py 8080 incumbent

printf '+ printf "PORT=8081\\n" > /tmp/app.env\n'
printf 'PORT=8081\n' > /tmp/app.env
expect 0 config-after cat /tmp/app.env
source /tmp/app.env
start_child app-after python3 /lab/scenarios/tcp_service.py app "$PORT"
app=$child
wait_ready "$app" app-after
expect 0 app-after-log cat "$OUT/app-after.txt"
expect 0 ss-after ss -ltnp '( sport = :8080 or sport = :8081 )'
expect 0 connect-after python3 /lab/tools/probe.py 8081 app
expect 0 incumbent-after python3 /lab/tools/probe.py 8080 incumbent
expect 0 app-alive kill -0 "$app"
expect 0 incumbent-alive kill -0 "$incumbent"
printf '{"scenario":"port","bind_failure_exit":78,"connection_refused_exit":2,"fixed_port":8081,"app_response":"pass","incumbent_preserved":true}\n' > "$OUT/result.json"
