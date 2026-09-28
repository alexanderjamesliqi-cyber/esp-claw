from pathlib import Path
import argparse,hashlib,json,shutil,subprocess
root=Path(__file__).resolve().parents[3]
build=root/'application/edge_agent/build'
parser=argparse.ArgumentParser()
parser.add_argument('--output',type=Path,required=True,help='New release directory; an existing release is never overwritten')
parser.add_argument('--version',required=True)
parser.add_argument('--validation',type=Path)
args=parser.parse_args()
out=args.output
out.mkdir(parents=True,exist_ok=False)
for name in ['edge_agent.bin','system.bin']:
 shutil.copy2(build/name,out/name)
shutil.copytree(root/'integration/labplus/sdcard',out/'sdcard',dirs_exist_ok=True)
for name in ['README.md','PRODUCT.md']:
 shutil.copy2(root/'integration/labplus'/name,out/name)
licenses=out/'licenses';licenses.mkdir(exist_ok=True)
for name in ['OFL.txt','RobotoMono-OFL.txt']:
 shutil.copy2(root/'integration/labplus/assets'/name,licenses/name)
(out/'source.patch').write_bytes(subprocess.check_output(['git','diff','--binary','HEAD'],cwd=root))
# Capture the SDK changes and locked build inputs needed to reproduce this binary.
idf=Path('/Users/james/esp32-build/esp-idf-v5.5.4')
(out/'esp-idf.patch').write_bytes(subprocess.check_output(['git','diff','--binary','HEAD'],cwd=idf))
config=out/'build-config';config.mkdir()
for name in ['sdkconfig','dependencies.lock','partitions_16MB.csv']:
 shutil.copy2(root/'application/edge_agent'/name,config/name)
(config/'revisions.json').write_text(json.dumps({'esp_idf':subprocess.check_output(['git','rev-parse','HEAD'],cwd=idf,text=True).strip(),'micropython':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root/'components/micropython_source',text=True).strip()},indent=2))
source=out/'source-additions';source.mkdir(exist_ok=True)
for raw in subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z'],cwd=root).split(b'\0'):
 if not raw:continue
 rel=Path(raw.decode())
 if str(rel).startswith(('integration/','components/','application/')):
  target=source/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/rel,target)
validation=out/'validation';validation.mkdir(exist_ok=True)
tests=Path('/Users/james/esp32-build/device-test-20260927')
for name in ['startup-validation.json','product-stress-validation.json','voice-memory-validation.json','resource-failure-validation.json','countdown-generation-validation.json','countdown-natural-validation.json','product-host-tests.log']:
 if (tests/name).exists():shutil.copy2(tests/name,validation/name)
screens=out/'screenshots';screens.mkdir(exist_ok=True)
for name in ['home','settings','library']:
 image=tests/('product-v3-'+name)/'frame.png'
 if image.exists():shutil.copy2(image,screens/(name+'.png'))
if args.validation:
 for name in ['STABILITY.md','memory-trace.png','fault-results.json','fault-monitor.json','repl-results.json','soak-results.json','soak-monitor.json','host-tests.log','final-validation.json','build-identity.json','test-provenance.json','display-results.json','display-monitor.json','playback-results.json','playback-monitor.json','startup-validation.json','countdown-validation.json','usb-burst-results.json','usb-burst-before.json','boot-validation.json','cooperative-core.patch','scan-results.json','scan-profile-results.json','scan-monitor.json','usb-fifo-host.log','upload-recovery-results.json','upload-abort-before.json','voice-concurrency-results.json','websocket-gc-results.json','usb-voice-concurrency-results.json','usb-voice-concurrency-monitor.json']:
  file=args.validation/name
  if file.is_file():shutil.copy2(file,validation/name)
 hardware=validation/'hardware-tests';hardware.mkdir(exist_ok=True)
 for name in ['make_report.py','rig.py','qa_api.lua','qa_soak.lua','run_faults.py','run_repl.py','run_display.py','run_playback.py','run_startup.py','run_startup_inner.py','run_soak.py','run_usb_burst.py','run_scan_probe.py','run_upload_recovery.py','run_voice_concurrency.py','run_websocket_gc.py','run_usb_voice_concurrency.py','run_countdown.py','qa_arithmetic.py']:
  file=args.validation/name
  if file.is_file():shutil.copy2(file,hardware/name)
 for file in [Path('/Users/james/esp32-build/runtime/tools/device.py'),Path('/Users/james/esp32-build/device-test-20260927/product_check.py')]:
  if file.is_file():shutil.copy2(file,hardware/file.name)
 (hardware/'README.md').write_text('真机破坏性故障注入测试，仅在专用测试板上运行。修改 rig.py/product_check.py 的设备 IP 和 device.py 的串口路径，安装 pyserial。先运行 run_faults.py，再运行其余测试；run_soak.py 至少持续 20 分钟。run_startup.py 会暂时修改开机选择并重启，结束后恢复。脚本上传 qa_ 临时文件，测试完成需清理。不要在运行用户任务时执行。')
 image=args.validation/'final-screen/frame.png'
 if image.is_file():shutil.copy2(image,screens/'home-current.png')
(out/'INSTALL.md').write_text('''# 本机工程交付版

适用于 Labplus 乐动 Max ESP32-P4、现有分区表及 ota_0。
仅将 edge_agent.bin 写入 0x20000，并将 sdcard/ 合并部署到设备 SD 根目录。
保留已有用户程序、配置、Wi-Fi 与密钥。不要使用全量默认 flash 命令覆盖 storage/NVS。
scheduler/、router_rules/ 是初始配置模板，已有设备不能直接覆盖其用户配置。
本次设备实际更新的是应用和 SD 文件；system.bin 是配套构建产物，本次未写入设备。
完整回滚使用开发机保存的原始全 Flash 与相应 SD 备份。
重建需使用 build-config/revisions.json 的 SDK/MicroPython 提交，并应用 source.patch、source-additions/ 和 esp-idf.patch。
build-config/ 保存本次 sdkconfig 与依赖锁。SDK 补丁包含 P4 USB FIFO 修正，不能遗漏；可运行 integration/labplus/tests/usb_fifo_access.py 检查。

程序库：点击作品预览，可设为开机程序；顶部“开机程序”可管理或取消。
底部上滑停止程序并回到主页，保留开机选择。
主界面显示时钟和连接状态；下拉仅提供设置。

validation/ 是工程回归记录，不代表量产认证或长期老化测试。
''')
manifest={'version':args.version,'board':'labplus_ledong_max_v1','chip':'ESP32-P4 rev3.2','base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),'app_offset':'0x20000','app_partition_size':'0x500000','deployment':'app and sdcard resources; NVS/OTA metadata/storage preserved','files':{}}
for p in sorted(out.rglob('*')):
 if p.is_file() and p.name!='manifest.json':manifest['files'][str(p.relative_to(out))]=hashlib.sha256(p.read_bytes()).hexdigest()
(out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
print(out)
