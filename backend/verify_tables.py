from models.database import engine
from sqlalchemy import inspect

inspector = inspect(engine)
tables = inspector.get_table_names()

print("All tables in database:")
for table in sorted(tables):
    print(f"  - {table}")

if 'dynamic_agents' in tables and 'generated_tools' in tables:
    print("\n✓ Dynamic agent tables exist!")
    
    # Show columns
    print("\nColumns in dynamic_agents:")
    for col in inspector.get_columns('dynamic_agents'):
        print(f"  - {col['name']}: {col['type']}")
    
    print("\nColumns in generated_tools:")
    for col in inspector.get_columns('generated_tools'):
        print(f"  - {col['name']}: {col['type']}")
else:
    print("\n✗ Tables missing!")