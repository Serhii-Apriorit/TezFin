import smartpy as sp

Guard = sp.io.import_script_from_url("file:contracts/GuardComptroller.py")
BlockLevel = sp.io.import_script_from_url(
    "file:contracts/tests/utils/BlockLevel.py")
CTMock = sp.io.import_script_from_url(
    "file:contracts/tests/mock/CTokenMock.py")


def redeemParams(cToken, redeemer, amount=sp.nat(1)):
    # 4f6121a ABI: redeemAmount (not redeemTokens / exchangeRateMantissa).
    return sp.record(
        cToken=cToken,
        redeemer=redeemer,
        redeemAmount=amount,
    )


@sp.add_test(name="GuardComptroller_Tests")
def test():
    bLevel = BlockLevel.BlockLevel()
    scenario = sp.test_scenario()
    scenario.add_flag("protocol", "lima")

    scenario.h1("Lean Guard Comptroller tests")

    admin = sp.test_account("admin")
    alice = sp.test_account("alice")
    bob = sp.test_account("bob")
    oldComptroller = sp.test_account("oldComptroller")

    exchRate = sp.nat(int(1e18))
    marketA = CTMock.CTokenMock(test_account_snapshot_=sp.record(
        account=alice.address,
        cTokenBalance=sp.nat(10),
        borrowBalance=sp.nat(0),
        exchangeRateMantissa=exchRate,
    ))
    marketB = CTMock.CTokenMock(test_account_snapshot_=sp.record(
        account=alice.address,
        cTokenBalance=sp.nat(0),
        borrowBalance=sp.nat(0),
        exchangeRateMantissa=exchRate,
    ))
    scenario += marketA
    scenario += marketB

    cmpt = Guard.GuardComptroller(
        administrator_=admin.address,
        markets_=[marketA.address, marketB.address],
        approvedRollbackComptroller_=oldComptroller.address,
    )
    scenario += cmpt

    listed = marketA.address
    collateral = marketB.address
    unlisted = sp.address("KT1UnlistedMarket1111111111111111111")

    scenario.h2("Repay is allowed on a listed market")
    scenario += cmpt.repayBorrowAllowed(sp.record(
        cToken=listed,
        payer=alice.address,
        borrower=alice.address,
        repayAmount=sp.nat(1),
    )).run(sender=listed, level=bLevel.next())

    scenario.h2("Repay rejects an unlisted market")
    scenario += cmpt.repayBorrowAllowed(sp.record(
        cToken=unlisted,
        payer=alice.address,
        borrower=alice.address,
        repayAmount=sp.nat(1),
    )).run(sender=alice.address, level=bLevel.next(), valid=False)

    scenario.h2("Mint / borrow / transfer / liquidation are disabled")
    level = bLevel.next()
    scenario += cmpt.mintAllowed(sp.record(
        cToken=listed, minter=alice.address, mintAmount=sp.nat(1)
    )).run(sender=listed, level=level, valid=False)
    scenario += cmpt.borrowAllowed(sp.record(
        cToken=listed, borrower=alice.address, borrowAmount=sp.nat(1)
    )).run(sender=listed, level=level, valid=False)
    scenario += cmpt.transferAllowed(sp.record(
        cToken=listed,
        src=alice.address,
        dst=bob.address,
        transferTokens=sp.nat(1),
    )).run(sender=listed, level=level, valid=False)
    scenario += cmpt.liquidateBorrowAllowed(sp.record(
        cTokenBorrowed=listed,
        cTokenCollateral=collateral,
        borrower=alice.address,
        liquidator=bob.address,
        repayAmount=sp.nat(1),
    )).run(sender=listed, level=level, valid=False)

    scenario.h2("Enter / exit market are disabled")
    scenario += cmpt.enterMarkets([listed]).run(
        sender=alice.address, level=level, valid=False)
    scenario += cmpt.exitMarket(listed).run(
        sender=alice.address, level=level, valid=False)

    scenario.h2("removeFromLoans is a no-op for listed market callers")
    scenario += cmpt.removeFromLoans(alice.address).run(
        sender=listed, level=bLevel.next())

    scenario.h2("Redeem fails when accrual is stale")
    staleLevel = bLevel.next()
    scenario += marketA.setAccrualBlockNumber(0).run(sender=admin)
    scenario += cmpt.redeemAllowed(
        redeemParams(listed, alice.address)
    ).run(sender=listed, level=staleLevel, valid=False)

    scenario.h2("First fresh redeem succeeds for a debt-free account")
    freshLevel = bLevel.next()
    scenario += marketA.setAccrualBlockNumber(freshLevel).run(sender=admin)
    scenario += marketA.setBorrowBalance(0).run(sender=admin)
    scenario += marketB.setBorrowBalance(0).run(sender=admin)
    scenario += cmpt.redeemAllowed(
        redeemParams(listed, alice.address)
    ).run(sender=listed, level=freshLevel)

    scenario.h2("Second same-market redeem in the same block fails")
    scenario += cmpt.redeemAllowed(
        redeemParams(listed, alice.address)
    ).run(sender=listed, level=freshLevel, valid=False)

    scenario.h2("Next-block redeem succeeds after fresh accrual")
    nextLevel = bLevel.next()
    scenario += marketA.setAccrualBlockNumber(nextLevel).run(sender=admin)
    scenario += cmpt.redeemAllowed(
        redeemParams(listed, alice.address)
    ).run(sender=listed, level=nextLevel)

    scenario.h2("Borrower redeem is blocked until debt is zero across markets")
    debtLevel = bLevel.next()
    scenario += marketA.setAccrualBlockNumber(debtLevel).run(sender=admin)
    scenario += marketB.setBorrowBalance(5).run(sender=admin)
    scenario += cmpt.redeemAllowed(
        redeemParams(listed, alice.address)
    ).run(sender=listed, level=debtLevel, valid=False)

    scenario += marketB.setBorrowBalance(0).run(sender=admin)
    debtClearLevel = bLevel.next()
    scenario += marketA.setAccrualBlockNumber(debtClearLevel).run(sender=admin)
    scenario += cmpt.redeemAllowed(
        redeemParams(listed, alice.address)
    ).run(sender=listed, level=debtClearLevel)

    scenario.h2("Governance can pause market redeem")
    pausedLevel = bLevel.next()
    scenario += cmpt.setMarketRedeemPaused(sp.record(
        cToken=listed, state=True
    )).run(sender=admin.address, level=pausedLevel)
    scenario += marketA.setAccrualBlockNumber(pausedLevel).run(sender=admin)
    scenario += cmpt.redeemAllowed(
        redeemParams(listed, alice.address)
    ).run(sender=listed, level=pausedLevel, valid=False)
    scenario += cmpt.setMarketRedeemPaused(sp.record(
        cToken=listed, state=False
    )).run(sender=admin.address, level=pausedLevel)

    scenario.h2("seizeAllowed is false in incident mode")
    scenario.verify(
        sp.view(
            "seizeAllowed",
            cmpt.address,
            sp.record(cTokenCollateral=collateral, cTokenBorrowed=listed),
            t=sp.TBool,
        ).open_some() == False
    )

    scenario.h2("Rollback helper only accepts the approved Comptroller")
    scenario += cmpt.verifyRollbackComptroller(oldComptroller.address).run(
        sender=admin.address, level=bLevel.next())
    scenario += cmpt.verifyRollbackComptroller(alice.address).run(
        sender=admin.address, level=bLevel.next(), valid=False)

    scenario.h2("supportMarket lists a market with redeem enabled")
    extra = sp.address("KT1ExtraMarket111111111111111111111")
    scenario += cmpt.supportMarket(sp.record(
        cToken=extra, name="extra", priceExp=sp.nat(int(1e18))
    )).run(sender=admin.address, level=bLevel.next())
    scenario.verify(cmpt.data.markets[extra].isListed)
    scenario.verify(cmpt.data.markets[extra].redeemPaused == False)

    scenario.h2("Repay remains allowed after supportMarket")
    scenario += cmpt.repayBorrowAllowed(sp.record(
        cToken=extra,
        payer=bob.address,
        borrower=alice.address,
        repayAmount=sp.nat(10),
    )).run(sender=extra, level=bLevel.next())
