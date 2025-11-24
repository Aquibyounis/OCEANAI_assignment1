from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from helpers import (
    get_llm, 
    load_chroma, 
    clean_and_parse_json
)

def generate_test_cases(db_id, query):
    try:
        db = load_chroma(db_id)
    except:
        return {"error": "DB not found"}

    results = db.similarity_search(query, k=6)
    context_text = "\n\n".join([
        f"Source: {doc.metadata.get('source', 'Unknown')}\nContent: {doc.page_content}" 
        for doc in results
    ])

    llm = get_llm()
    prompt = ChatPromptTemplate.from_template(
        """
You are a Senior QA Lead.
CONTEXT: {context}
REQUEST: {query}

INSTRUCTIONS:
1. Analyze the HTML deeply.
2. Generate ONLY test cases that can be executed using the given HTML structure.
3. DO NOT include any steps that involve:
   - filling checkout form
   - clicking Pay
   - submitting checkout
   unless the user explicitly requests a checkout test.
4. Steps should reflect ONLY elements visible in HTML.
5. Steps MUST NOT go beyond the test case goal.
6. Always consider visibility flow:
   - cart-summary is hidden until item added
   - discount section is inside cart-summary
7. FORMAT RULE: Output only RAW JSON ARRAY.
8. Each object MUST contain:
   - id
   - title
   - description
   - preconditions
   - steps (ARRAY OF STRINGS, not one string)
   - expected_result
   - source_file
9. Generate steps inside based on intent of title, Strictly based on TITLE
10. Tell if there will be any alerts inside the steps too like when something trigger alert or message then what to do strictly based on existing html.

OUTPUT FORMAT EXAMPLE (USE THIS EXACT NEWLINE STYLE):

[
  {{
    "id": "TC001",
    "title": "Verify Discount Code",
    "description": "Enter 'SAVE15' and check if price updates",
    "preconditions": "Cart must have items",
    "steps": [
      "Add item to cart",
      "Wait for cart summary to be visible",
      "Enter 'SAVE15'",
      "Click Apply",
      "Verify price is reduced"
    ],
    "expected_result": "Total reduced by 15%",
    "source_file": "checkout.html"
  }}
]
OR 
OUTPUT FORMAT EXAMPLE (USE THIS EXACT NEWLINE STYLE):

[
  {{
    "id": "TC001",
    "title": "Verify Empty cart code",
    "description": "Cart is empty return issue",
    "preconditions": "Cart must be empty",
    "steps": [
      "dont add items to cart. leave it empty." 
      "Check for cart if not found return cart empty",
    ],
    "expected_result": "Cart is empty",
    "source_file": "checkout.html"
  }}
]

REQUIREMENTS ABOUT NEWLINES:
- NO empty lines inside JSON objects
- ONE blank line AFTER the array example
- Steps MUST be an array with ONE step per string
- NO trailing commas anywhere
- NO markdown formatting
- NO explanation

        """
    )

    chain = prompt | llm | StrOutputParser()
    raw = chain.invoke({"context": context_text, "query": query})
    return clean_and_parse_json(raw)