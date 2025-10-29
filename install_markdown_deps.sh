#!/bin/bash

# AI Analysis Result Markdown Rendering Dependencies Installation Script

echo "=========================================="
echo "Installing Markdown & Code Highlighting Dependencies"
echo "=========================================="
echo ""

# Navigate to frontend directory
cd frontend || exit 1

echo "📦 Installing dependencies..."
npm install

echo ""
echo "✅ Installation complete!"
echo ""
echo "📝 Installed packages:"
echo "  - markdown-it: Professional markdown parser"
echo "  - highlight.js: Code syntax highlighting"
echo "  - @types/markdown-it: TypeScript definitions"
echo ""
echo "🚀 Next steps:"
echo "  1. Run 'npm run dev' to start the development server"
echo "  2. Test AI analysis functionality"
echo "  3. Check MARKDOWN_REFACTOR_README.md for detailed documentation"
echo ""
echo "=========================================="
