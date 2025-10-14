# Type-aware LLM-based Regression Test Generation for Python Programs

This repository contains the tools and experimental results mentioned in the paper.

## 💡Overview

Automated regression test generation has been extensively explored, yet generating high-quality tests for Python programs remains particularly challenging. 
Existing approaches, ranging from search-based software testing (SBST) to recent LLM-driven techniques, are often prone to type errors, resulting in invalid inputs and semantically inconsistent test cases, which ultimately undermine their practical effectiveness. 
To address these limitations, we present Test4Py, a novel framework that enhances type correctness in automated test generation. 
Test4Py leverages the program’s call graph to capture richer contextual information about parameters, and introduces a behavior-based type inference mechanism that accurately infers parameter types and construct valid test inputs. 
Beyond input construction, Test4Py integrates an iterative repair procedure
that progressively refines generated test cases to improve coverage. 
In an evaluation on 183 real-world Python modules, Test4Py achieved an average statement coverage of 83.0% and branch coverage of 70.8%, outperforming state-of-the-art tools by 7.2% and 8.4%, respectively.

* Directory `ex-results` contains experimental results.

## 🎬Requirements

### 1. Install requirements

```angular2html
pip install -r requirements.txt
```

### 2. Install transformer

Download files from [here](https://huggingface.co/BAAI/bge-large-en-v1.5/tree/main).

Needed files are as follows:

```
config.json
pytorch_model.bin
special_token_map.json
tokenizer.json
tokenizer_config.json
vocab.txt
```

Change value of `TRANSFORMER_PATH` in `.env` to the path where these files above are.

### 3. Add Python path

Change value of `USER_PYTHON_PATH` in `.env` to the path where your Python is.

In this Python environment, you need to install all dependencies for the project under test and run the following commands:

```angular2html
pip install pytest
pip install coverage
pip install pylint
pip install pytest-json-report
```

### 4. Add OPENAI_API_KEY and OPENAI_API_BASE

Generate your own `OPENAI_API_KEY` and `OPENAI_API_BASE` , and add them into `.env` file.

## 🚀Quick Start

Ensure that the project under test can successfully run using the Python environment specified by `USER_PYTHON_PATH`.

And If you are using Windows, you need to run ***Test4Py*** in WSL.

If your project's path is `project_dir` and the source code is located under `src`, you can run Test4Py like this: 
```shell
$ python -m test4dt.start --project_path project_dir --source_path src
```

## 🔥Experimental Results

Original experimental data can be viewed at [Experimental Data](/ex-results).

### RQ1: How does Test4Py compare with state-of-the-art baselines in terms of code coverage?

Test4Py consistently achieves higher and more stable coverage than state-of-the-art baselines. 
Its advantages are especially pronounced in scenarios without type hints, underscoring its effectiveness in dynamically typed settings.

### RQ2: How do different large language models affect the performance of Test4Py in test generation?

Different LLMs have a measurable impact on the performance of Test4Py.
Deepseek demonstrates the highest coverage, followed by gpt-4o and qwen. We further evaluated state-of-the-art baselines across the same models and observed that Test4Py exhibits greater stability across model variations, highlighting its stronger robustness to differences in underlying LLM capabilities.

### RQ3: How effective is Test4Py ’s type inference module compared to existing type inference tools, and what is its impact through ablation analysis?

Test4Py’s type inference is more effective than Hityper and LLM-Only, especially when handling user-defined types. 
Additionally, the type inference system enables Test4Py to achieve better performance in the absence of type annotations.

### RQ4: How does incorporating call graph-guided summaries influence the effectiveness of test case generation in Test4Py?

Call graph-guided summaries improve both branch coverage and mutation score, thereby enhancing the semantic adequacy and fault-detection capability of the generated test cases.

### RQ5: How does error repair and iterative test case generation improve the quality of test suites produced by Test4Py?

Automated repair substantially mitigates both syntax- and semantics-related errors, ensuring that the final test suite is both comprehensive and reliable. 
Although Test4Py incurs a higher execution cost, the resulting increase in coverage and suite quality justifies the additional time.
