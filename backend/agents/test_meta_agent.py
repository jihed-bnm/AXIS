"""Test script for the meta-agent"""
import json
import sys
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from agents.meta_agent import run_meta_agent

def main():
    print("=" * 80)
    print("Testing Meta-Agent: Project Milestone Tracking")
    print("=" * 80)
    
    domain_description = """
    Create an agent for managing project milestones and tracking deliverable deadlines.
    The agent should help users view upcoming milestones, check overdue deliverables,
    and get project progress summaries.
    """
    
    print("\nDomain Request:")
    print(domain_description)
    print("\n" + "=" * 80)
    print("Running meta-agent (this may take 20-30 seconds)...\n")
    
    try:
        result = run_meta_agent(
            domain_description=domain_description.strip(),
            created_by=1  # Test user ID
        )
        
        print("✓ Meta-agent completed successfully!\n")
        print("=" * 80)
        print("GENERATED AGENT SPECIFICATION")
        print("=" * 80)
        
        print(f"\nAgent Name: {result['agent_name']}")
        print(f"Status: {result['status']}")
        print(f"Database ID: {result['agent_id']}")
        
        print(f"\nDescription:")
        print(f"  {result['description']}")
        
        print(f"\nSystem Prompt:")
        print(f"  {result['system_prompt'][:200]}...")
        
        print(f"\nKeyword Rules ({len(result['keyword_rules'])} keywords):")
        print(f"  {', '.join(result['keyword_rules'])}")
        
        print(f"\nGenerated Tools ({len(result['tools'])} tools):")
        for i, tool in enumerate(result['tools'], 1):
            print(f"\n  Tool {i}: {tool['name']}")
            print(f"    Description: {tool['description']}")
            print(f"    Parameters: {list(tool['parameters_schema'].keys())}")
            print(f"    Validation: {tool['validation_status']}")
            if tool['validation_status'] == 'passed':
                print(f"    ✓ AST validation passed")
                print(f"    ✓ SQL safety check passed")
            else:
                print(f"    ✗ Validation failed: {tool.get('validation_error', 'Unknown')}")
        
        print("\n" + "=" * 80)
        print("GENERATED TOOL CODE (First Tool)")
        print("=" * 80)
        if result['tools']:
            print(result['tools'][0]['code'])
        
        print("\n" + "=" * 80)
        print("FULL JSON OUTPUT")
        print("=" * 80)
        print(json.dumps(result, indent=2))
        
    except Exception as e:
        print(f"✗ Meta-agent failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()