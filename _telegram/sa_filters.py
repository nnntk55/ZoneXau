import subprocess, os, time, json, sys
CLI=r"C:\Users\Administrator\AppData\Local\Spotware\cTrader\abb70432efbee65d18af69e79fe8efe1\app_5.10.22.54872\ctrader-cli.exe"
PW=r"C:\Users\Administrator\Desktop\devin_work\ZoneXau\_telegram\ctid_pwd.txt"
OUT=r"C:\Users\Administrator\Desktop\devin_work\ZoneXau\_telegram\bt_results"
ALGO=r"C:\Users\Administrator\Documents\cAlgo\Sources\Robots\SnackbabyA.algo"
env=dict(os.environ); env["DOTNET_ROOT"]=r"C:\Users\Administrator\AppData\Local\Spotware\dotnet"
BASE=["--UseCross=True","--SlUsd=8","--TrailStep=2.7","--TrailOff=0.3"]
RUNS=[
 ("sa_f_base", []),
 ("sa_f_z", ["--UseZScore=True","--ZLen=50","--ZMax=2"]),
 ("sa_f_cd", ["--CooldownLosses=2","--CooldownSignals=1"]),
 ("sa_f_zcd", ["--UseZScore=True","--ZLen=50","--ZMax=2","--CooldownLosses=2","--CooldownSignals=1"]),
 ("sa_dema", ["--UseDayEma=True","--DayEmaLen=50","--UseDayStoch=True"]),
 ("sa_dstoch", ["--UseM5EmaBias=False","--UseDayStoch=True"]),
 ("sa_dayboth", ["--UseM5EmaBias=False","--UseDayEma=True","--DayEmaLen=50","--UseDayStoch=True"]),
 ("sa_bbw", ["--UseBbwGate=True","--BbwMin=0.06"]),
 ("sa_bbwd", ["--UseBbwGate=True","--BbwMin=0.06","--UseDayEma=True","--DayEmaLen=50","--UseDayStoch=True"]),
 ("sa_adx", ["--UseAdxGate=True","--AdxMin=30"]),
 ("sa_adxd", ["--UseAdxGate=True","--AdxMin=30","--UseDayEma=True","--DayEmaLen=50","--UseDayStoch=True"]),
]
START=sys.argv[1] if len(sys.argv)>1 else "09/10/2026"
END=sys.argv[2] if len(sys.argv)>2 else "09/11/2026"
TAG=sys.argv[3] if len(sys.argv)>3 else ""
ONLY=sys.argv[4:]
runs=[r for r in RUNS if not ONLY or any(t in r[0] for t in ONLY)]
n=len(runs)
for k,(name,extra) in enumerate(runs,1):
    name=name+TAG
    print(f"[progress] {k}/{n} {name}",flush=True)
    cmd=[CLI,"backtest",ALGO,"--ctid=ninin.natakrit@gmail.com",f"--pwd-file={PW}","--account=3002363",
         "--symbol=XAUUSD","--period=m5",f"--start={START}",f"--end={END}","--data-mode=m1",
         "--balance=10000",f"--report-json={os.path.join(OUT,name)}.json","--equity-x-axis=Trades"]+BASE+extra
    report=os.path.join(OUT,name)+".json"
    if os.path.exists(report): os.remove(report)
    p=subprocess.Popen(cmd,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    t0=time.time(); out=""
    while time.time()-t0<1800:
        if p.poll() is not None: break
        if os.path.exists(report) and time.time()-os.path.getmtime(report)>10: break
        time.sleep(5)
    try: out,_=p.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill(); out,_=p.communicate()
    print((out or "")[-400:],flush=True)
    subprocess.run(["taskkill","/F","/IM","ctrader-cli.exe"],capture_output=True)
    subprocess.run(["taskkill","/F","/IM","algohost.exe"],capture_output=True)
print("[progress] done",flush=True)
