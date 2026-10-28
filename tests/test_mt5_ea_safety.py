import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
EA = (ROOT / "mt5" / "CandleBehaviourEA.mq5").read_text()
GUIDE = (ROOT / "docs" / "MT5_EA_DEMO.md").read_text()


class Mt5EaSafetyTests(unittest.TestCase):
    def test_live_account_is_blocked(self):
        self.assertIn("DemoAccountOnly=true", EA)
        self.assertIn("ACCOUNT_TRADE_MODE_DEMO", EA)
        self.assertIn("return INIT_FAILED", EA)

    def test_demo_execution_enabled_and_rr_minimum(self):
        self.assertIn("input bool EnableTrading=true", EA)
        self.assertIn("input bool UseFixedLotSize=true", EA)
        self.assertIn("input double FixedLotSize=0.01", EA)
        self.assertIn("bool ConfirmM5(", EA)
        self.assertIn("bool M1Entry(", EA)
        self.assertIn("MinimumRewardRisk<3.0", EA)
        self.assertIn("reward/risk+1e-8<MinimumRewardRisk", EA)

    def test_trade_management_and_minimum_lot(self):
        self.assertIn("input double FixedLotSize=0.01", EA)
        self.assertIn("input bool EnableProfitProtection=true", EA)
        self.assertIn("input bool CloseOnM1Reversal=true", EA)
        self.assertIn("void ManageOpenTrade()", EA)
        self.assertIn("trade.PositionModify(_Symbol,wanted,tp)", EA)
        self.assertIn("trade.PositionClose(_Symbol)", EA)
        self.assertIn("ManageOpenTrade();", EA)
        self.assertIn("two opposing M1 candles", GUIDE)

    def test_risk_guards(self):
        self.assertIn("RiskPercent", EA)
        self.assertIn("LossLimit()", EA)
        self.assertIn("tradesToday>=MaxTradesPerDay", EA)
        self.assertIn("OurPosition()", EA)
        self.assertIn("if(raw<minLot)return 0", EA)
        self.assertIn("if(UseFixedLotSize)", EA)

    def test_docs_are_honest_about_prototype(self):
        self.assertIn("not approved for live trading", GUIDE)
        self.assertIn("not a proven exact replica", GUIDE)
        self.assertIn("untouched chronological holdout", GUIDE)


if __name__ == "__main__":
    unittest.main()
