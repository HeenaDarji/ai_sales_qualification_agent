"""Unit tests for deterministic pricing calculation, heuristic extraction, and Pydantic models.

Compatible with both `pytest` and Python's built-in `unittest`.
All tests run completely offline without requiring a Gemini API key.
"""

import unittest
from pydantic import ValidationError

from core.schemas import SalesLeadQualification, ToolResult
from core.tools import (
    calculate_price_estimate,
    extract_lead_heuristics,
    parse_budget_numeric,
)


class TestPriceEstimateTool(unittest.TestCase):
    """Tests for calculate_price_estimate function."""

    def test_starter_base_price_under_ten_seats(self):
        """Teams of 10 or fewer seats should be charged the base rate of ₹25,000."""
        result = calculate_price_estimate(requirements="Basic chatbot", seats=5, budget=30000)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.tool_name, "calculate_price_estimate")
        self.assertEqual(result.plan, "Starter Plan")
        self.assertEqual(result.estimated_price_inr, 25000)
        self.assertIn("covers up to 10 seats", result.message)

    def test_additional_seats_surcharge_calculation(self):
        """Test Case 1 scenario: 35 agents with ₹80,000 budget."""
        # 35 agents: 10 base + 25 extra seats * ₹2,000 = ₹50,000 extra
        # Starter plan base ₹25,000 + ₹50,000 = ₹75,000 total (within ₹80,000 budget)
        result = calculate_price_estimate(
            requirements="AI customer-support solution for 35 agents",
            seats=35,
            budget=80000,
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.plan, "Starter Plan")
        self.assertEqual(result.estimated_price_inr, 75000)
        self.assertIn("25 additional seat(s) @ ₹2,000", result.message)

    def test_professional_plan_selection(self):
        """Professional plan should be selected when budget permits and higher tier is appropriate."""
        result = calculate_price_estimate(
            requirements="Operations support platform with integrations",
            seats=15,
            budget=70000,
        )
        # 15 seats -> 5 extra seats * 2,000 = ₹10,000. Pro base = ₹50,000. Total = ₹60,000 <= ₹70,000.
        self.assertEqual(result.status, "success")
        self.assertEqual(result.plan, "Professional Plan")
        self.assertEqual(result.estimated_price_inr, 60000)

    def test_enterprise_plan_selection_by_keywords(self):
        """Enterprise plan should be selected when explicit enterprise requirements exist."""
        result = calculate_price_estimate(
            requirements="Enterprise solution with custom SLA and security audit",
            seats=20,
            budget=150000,
        )
        # 20 seats -> 10 extra seats * 2,000 = ₹20,000. Enterprise base = ₹100,000. Total = ₹120,000.
        self.assertEqual(result.status, "success")
        self.assertEqual(result.plan, "Enterprise Plan")
        self.assertEqual(result.estimated_price_inr, 120000)

    def test_no_seats_specified_defaults_gracefully(self):
        """When seats is null, tool provides base estimate and notes that team size is needed."""
        result = calculate_price_estimate(requirements="General AI solution", seats=None, budget=None)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.estimated_price_inr, 25000)
        self.assertIn("Team size / seat count not specified", result.message)

    def test_simulate_tool_failure(self):
        """Simulate tool failure must return structured error object."""
        result = calculate_price_estimate(
            requirements="AI Support",
            seats=35,
            budget=80000,
            simulate_failure=True,
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.tool_name, "calculate_price_estimate")
        self.assertIsNone(result.plan)
        self.assertIsNone(result.estimated_price_inr)
        self.assertIn("temporarily unavailable", result.message)


class TestHeuristicsExtractor(unittest.TestCase):
    """Tests for regex-based text heuristic extraction."""

    def test_extract_case_1_qualified_lead(self):
        text = """Hi, I am Riya Shah, Operations Manager at BrightCart.
You can contact me at riya@brightcart.com.
We need an AI customer-support solution for 35 agents.
Our budget is ₹80,000 and we want to start within 3 months."""

        data = extract_lead_heuristics(text)
        self.assertEqual(data["customer_name"], "Riya Shah")
        self.assertEqual(data["contact_details"], "riya@brightcart.com")
        self.assertEqual(data["seats"], 35)
        self.assertEqual(data["budget_num"], 80000)
        self.assertEqual(data["timeline"], "within 3 months")
        self.assertFalse(data["contradiction_detected"])

    def test_extract_case_2_missing_details(self):
        text = "We need an AI solution for our company. Please contact me."
        data = extract_lead_heuristics(text)
        self.assertIsNone(data["seats"])
        self.assertIsNone(data["budget_num"])
        self.assertIsNone(data["timeline"])
        self.assertIsNone(data["contact_details"])

    def test_extract_case_3_contradictory_budget(self):
        text = """Our budget is ₹10,000, but finance approved ₹100,000.
We need a customer support solution next month."""
        data = extract_lead_heuristics(text)
        self.assertTrue(data["contradiction_detected"])
        self.assertEqual(data["timeline"], "next month")
        self.assertIn("Contradictory values detected", data["budget_str"])

    def test_parse_budget_numeric_variations(self):
        self.assertEqual(parse_budget_numeric("₹80,000"), 80000)
        self.assertEqual(parse_budget_numeric("50k"), 50000)
        self.assertEqual(parse_budget_numeric("1.5 lakh"), 150000)
        self.assertEqual(parse_budget_numeric("Rs. 25000"), 25000)
        self.assertIsNone(parse_budget_numeric(None))


class TestPydanticSchemaValidation(unittest.TestCase):
    """Tests for Pydantic models and strict status validation."""

    def test_valid_qualified_payload(self):
        payload = {
            "customer_name": "Riya Shah",
            "contact_details": "riya@brightcart.com",
            "requirements": "AI support for 35 agents",
            "budget": "₹80,000",
            "timeline": "within 3 months",
            "customer_intent": "High buying interest",
            "lead_status": "Qualified",
            "classification_reason": "Clear requirements, budget meets ₹75,000 estimate, timeline within 3 months.",
            "missing_information": [],
            "follow_up_questions": ["Would you like a demonstration of the agent routing?"],
            "tool_result": {
                "status": "success",
                "tool_name": "calculate_price_estimate",
                "plan": "Starter Plan",
                "estimated_price_inr": 75000,
                "message": "Base plan + 25 extra seats",
            },
            "safety_note": None,
        }
        lead = SalesLeadQualification.model_validate(payload)
        self.assertEqual(lead.lead_status, "Qualified")
        self.assertEqual(lead.customer_name, "Riya Shah")
        self.assertEqual(lead.tool_result.estimated_price_inr, 75000)

    def test_valid_unqualified_payload(self):
        payload = {
            "customer_name": None,
            "contact_details": None,
            "requirements": "Student project inquiry",
            "budget": "₹5,000",
            "timeline": None,
            "customer_intent": "No commercial buying interest",
            "lead_status": "Unqualified",
            "classification_reason": "Budget of ₹5,000 is below the ₹20,000 threshold.",
            "missing_information": ["Timeline", "Contact Details"],
            "follow_up_questions": [],
            "tool_result": {
                "status": "success",
                "tool_name": "calculate_price_estimate",
                "plan": "Starter Plan",
                "estimated_price_inr": 25000,
                "message": "Base rate",
            },
            "safety_note": None,
        }
        lead = SalesLeadQualification.model_validate(payload)
        self.assertEqual(lead.lead_status, "Unqualified")

    def test_valid_needs_more_information_payload(self):
        payload = {
            "customer_name": None,
            "contact_details": None,
            "requirements": None,
            "budget": None,
            "timeline": None,
            "customer_intent": "General inquiry",
            "lead_status": "Needs More Information",
            "classification_reason": "Essential requirements, budget, and timeline are missing.",
            "missing_information": ["Requirements", "Budget", "Timeline"],
            "follow_up_questions": ["What is your expected timeline for implementation?"],
            "tool_result": {
                "status": "success",
                "tool_name": "calculate_price_estimate",
                "plan": "Starter Plan",
                "estimated_price_inr": 25000,
                "message": "Base rate",
            },
            "safety_note": None,
        }
        lead = SalesLeadQualification.model_validate(payload)
        self.assertEqual(lead.lead_status, "Needs More Information")

    def test_invalid_lead_status_rejected(self):
        """Pydantic should reject any status other than Qualified, Unqualified, or Needs More Information."""
        payload = {
            "customer_name": "John",
            "contact_details": "john@test.com",
            "requirements": "Test",
            "budget": "100000",
            "timeline": "1 month",
            "customer_intent": "Buying",
            "lead_status": "Pending Review",  # Invalid!
            "classification_reason": "Testing",
            "missing_information": [],
            "follow_up_questions": [],
            "tool_result": {
                "status": "success",
                "tool_name": "calculate_price_estimate",
                "plan": "Starter Plan",
                "estimated_price_inr": 25000,
                "message": "Test",
            },
            "safety_note": None,
        }
        with self.assertRaises(ValidationError):
            SalesLeadQualification.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
