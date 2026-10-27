"""Steps 3-6 of `livekit-wakeword run` — works around 0.3.0 calling run_extraction() without sess_options."""
import logging, sys
from onnxruntime import SessionOptions
from livekit.wakeword.config import load_config
from livekit.wakeword.data.features import run_extraction
from livekit.wakeword.training.trainer import run_train
from livekit.wakeword.export.onnx import run_export
from livekit.wakeword.eval.evaluate import run_eval

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
cfg = load_config(sys.argv[1])
# Default onnxruntime threads spin on every core (~19 of 20 busy); 4 non-spinning threads keep the desktop usable.
opts = SessionOptions(); opts.intra_op_num_threads = 4; opts.inter_op_num_threads = 1
opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
logging.info("Step 3/6: extract"); run_extraction(cfg, opts)
logging.info("Step 4/6: train"); run_train(cfg)
logging.info("Step 5/6: export"); run_export(cfg)
onnx = cfg.model_output_dir / f"{cfg.model_name}.onnx"
logging.info("Step 6/6: eval"); r = run_eval(cfg, onnx)
logging.info(f"Eval: AUT={r['aut']:.4f} FPPH={r['fpph']:.2f} Recall={r['recall']:.1%} -> {onnx}")
