import smartpy as sp

CFG = sp.io.import_script_from_url("file:deploy/compile_targets/Config.py")
GC = sp.io.import_script_from_url("file:contracts/GuardComptroller.py")

# Lean Guard only needs Governance as admin. Markets are listed after
# originate via supportMarket (or pass markets_ here for a fixed set).
sp.add_compilation_target(
    "GuardComptroller",
    GC.GuardComptroller(
        administrator_=sp.address(CFG.deployResult.Governance),
        approvedRollbackComptroller_=sp.address(CFG.deployResult.Comptroller)
        if hasattr(CFG.deployResult, "Comptroller") else None,
    ),
)
