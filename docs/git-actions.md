
flowchart TD
    A["You push code"] --> B["GitHub Actions starts"]
    B --> C["Install Python and uv"]
    C --> D["Install workspace dependencies"]
    D --> E["Run pytest"]
    E --> F{"Tests pass?"}
    F -->|No| G["Pipeline fails"]
    F -->|Yes| H["Build both packages"]
    H --> I["CI succeeds"]
    I --> J["You publish a GitHub Release"]
    J --> K["Publish radiodish to PyPI"]
    K --> L["Publish radiodish-actor to PyPI"]

