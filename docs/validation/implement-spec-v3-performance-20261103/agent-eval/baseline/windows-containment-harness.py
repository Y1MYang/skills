import sys, unittest, importlib.util, shutil
from pathlib import Path
source=Path(r"C:/Users/admin/AppData/Local/Temp/implement-spec-v3-baseline-20261103-144424-069/implement-spec-v3/tests/test_run_command.py")
spec=importlib.util.spec_from_file_location("frozen_tests",source); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
out=Path(__file__).parent/"windows-containment-artifacts"
class RetainedChecks(mod.RunCommandTests):
    def tearDown(self):
        dest=out/self._testMethodName
        dest.mkdir(parents=True,exist_ok=False)
        for f in self.base.iterdir():
            if f.is_file(): shutil.copy2(f,dest/f.name)
names=["test_timeout_stops_owned_tree_and_preserves_unrelated_process","test_normal_target_exit_cleans_still_running_descendant"]
suite=unittest.TestSuite(RetainedChecks(n) for n in names)
result=unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(not result.wasSuccessful())
