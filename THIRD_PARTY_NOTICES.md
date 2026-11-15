<!-- File purpose: Identify external content and preserve bundled frontend license notices. -->

# Third-party notices

The catalog stores LeetCode problem numbers, titles, curated tags, and official
links. The project does not include full problem statements or paid material.
Linked content and product names remain associated with their respective owners.
The project does not claim endorsement by LeetCode.

Python and SQLite are provided by the user's environment. The Skill bundle includes
this project's Python source. It does not bundle a Python interpreter or SQLite
binary. The core runtime has no third-party Python package dependencies.
Optional FastAPI, Uvicorn, and related Python packages are installed separately.
They are not copied into either Skill bundle.

The MIT license covers the original code and documentation in this project.
It does not relicense external content reached through catalog links.

## Optional compiled frontend

The Web build includes React, ReactDOM, and Scheduler from the React project.
Their exact versions are recorded in `web/package-lock.json` in the source tree.
Their installed packages carry the same MIT license notice, reproduced below.
This notice and this project's LICENSE are included in the built static files.

MIT License

Copyright (c) Meta Platforms, Inc. and affiliates.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
