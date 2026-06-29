---
id: "ai_tools_4_what_is_mcp"
category: "LLM工具调用面试题"
category_slug: "tools"
order: "4"
title: "什么是 MCP（模型上下文协议）？讲讲它的核心内容？"
url: "https://xiaolinnote.com/ai/tools/4_what_is_mcp.html"
fetched_at: "2026-06-13T22:11:54+08:00"
---

# 4. 什么是 MCP（模型上下文协议）？讲讲它的核心内容？

👔面试官：说说什么是 MCP？它的核心内容是什么？

🙋‍♂️我：MCP 就是一个工具调用框架吧，跟 Function Calling 差不多，都是让模型调用外部工具的。

👔面试官：MCP 是协议，不是框架，跟 Function Calling 更不是一个层面的东西。Function Calling 解决的是「模型怎么输出调用请求」，MCP 解决的是「工具怎么标准化接入」。你把这两个搞混了，说说 MCP 到底要解决什么问题？

🙋‍♂️我：呃……MCP 是为了让工具接入更方便？就是 Anthropic 搞的一个 API 标准，让 Claude 能调更多工具？

👔面试官：MCP 是开放协议，不是只给 Claude 用的。它解决的是工具接入碎片化的问题，工具实现一次、到处复用，任何支持 MCP 的客户端都能接入。Client-Server 架构、三类核心能力 Tools/Resources/Prompts 的区别、底层 JSON-RPC 通信机制，这些核心内容你一个都没提到，回去补课吧。

看来 MCP 这个概念确实容易和 Function Calling 搞混。下面我从「MCP 到底要解决什么问题」出发，把它的架构、三类核心能力、底层通信机制完整讲清楚。

## 💡 简要回答

MCP 是 Anthropic 在 2024 年底推出的开放协议，我理解它主要解决的是「模型接工具太碎片化」的问题。

在 MCP 出现之前，每接一个新工具都要单独写集成代码、处理认证、适配格式，而且这套代码和具体模型强绑定，换个模型就得重写，非常繁琐。

MCP 的思路是把这件事标准化：工具提供方按协议实现一个 Server，任何支持 MCP 的 AI 客户端就能直接接进来，一次实现到处复用。

协议定义了三类能力：Tools 用于执行有副作用的操作，Resources 是只读数据，Prompts 是提示词模板，底层通信用 JSON-RPC 2.0。

我把它理解成给「AI 接工具」这件事定了一套行业标准。

## 📝 详细解析

### 没有 MCP 之前，接工具有多麻烦

想象你要给 Claude 接入 GitHub 工具。你得手写 GitHub API 的调用代码、处理认证（OAuth token 怎么传）、处理各种返回格式、把 API 响应转成模型能理解的格式……好不容易接好了。

结果过了两个月，Claude 升了个版，接口有变化，你的对接代码得改。更麻烦的是，你同时接了十个工具，每个工具都有自己的一套对接代码，各自的格式、认证方式、错误处理逻辑都不一样。现在产品方说，这套工具也要给 Cursor 用，不好意思，你得重写一遍，因为 Cursor 和 Claude Desktop 的接入方式完全不同。

这就是 MCP 出现之前，AI 工具生态的真实状态：**碎片化、难复用、强绑定**。每个工具、每个模型都是一座孤岛，接一个新工具就要重新搭一座桥。

![Image](https://cdn.xiaolincoding.com//picgo/1772114354922-0796d37a-4925-4146-a221-2b2606644e83.png)

### MCP 的核心思路，定一套行业标准接口

MCP（Model Context Protocol，模型上下文协议）的设计思路，可以用 USB 接口来类比。在 USB 标准出现之前，鼠标用这个接口、键盘用那个接口、打印机又是另一个，换台电脑就要愁接口不兼容。USB 出现之后，所有外设统一接口，任何设备插到任何电脑都能工作，设备厂商只需要做一次适配，全球所有 USB 电脑都能用。

MCP 做的是同一件事：为「AI 接工具」这件事定了一套统一的协议标准。工具提供方（比如 GitHub 官方）按 MCP 规范实现一个 MCP Server，里面封装好各种操作。任何支持 MCP 的 AI 客户端，Claude Desktop、Cursor、各种 Agent 框架，都能直接连上这个 Server，自动发现里面的工具并使用，不需要写任何定制化对接代码。工具只需要实现一次，到处复用。

![Image](https://cdn.xiaolincoding.com//picgo/1776865581325-6f27789d-c506-4089-91ca-78a2711e89da.png)

### MCP 的 Client-Server 架构

MCP 采用标准的 Client-Server 架构。

Server 是工具的实现方。比如 GitHub 官方维护一个 GitHub MCP Server，里面封装了「列出 PR」「创建 Issue」「搜索仓库」「查看 Diff」等操作；Client 是 AI 应用那一侧，比如 Claude Desktop 或 Cursor，连上 Server 之后就自动获得了这些工具能力。

一个 Client 可以同时连接多个 Server。你把文件系统 Server + GitHub Server + PostgreSQL Server 都接上，模型就同时拥有了操作本地文件、读写代码仓库、查询数据库这三套工具能力，而你不需要写任何对接代码，只需要在配置文件里加几行 JSON，重启后 Claude 自动发现并使用这些工具。

![Image](https://cdn.xiaolincoding.com//picgo/1776865700094-9d7b71e7-b1b3-4b81-a63e-26d041d14622.png)

### 三类核心能力，Tools、Resources、Prompts

MCP Server 可以向 Client 暴露三类能力，各有各的定位。

![Image](https://cdn.xiaolincoding.com//picgo/image-20260304203844476.png?image_process=watermark,text_eGlhb2xpbm5vdGUuY29tQOWwj-ael-mdouivleeslOiusA,g_center,size_35,type_aHloZWk,color_304ffe?image_process=watermark,text_eGlhb2xpbm5vdGUuY29tQOWwj-ael-mdouivleeslOiusA,g_south,size_30,type_aHloZWk,color_304ffe)

先说 **Tools（工具）**，这是最核心的能力，对应 Function Calling 里的「函数」。Tools 的本质是「有副作用的操作」，什么叫有副作用？就是执行之后会改变外部世界的状态。创建文件、提交代码、发送 Slack 消息、调用第三方 API，这些都属于 Tools，因为执行完之后环境发生了变化，而且往往不可逆。正因为如此，Tools 通常需要用户授权确认才能执行，不能让模型想调就调。

再说 **Resources（资源）**，它和 Tools 最本质的区别就一个字：只「读」。Resources 不会改变任何东西，只是把数据提供给模型看。读取日志文件、查询数据库记录、获取文档内容，都属于 Resources 的范畴。你可以把 Resources 理解成「工具的资料室」，模型可以进去查资料，但不能修改里面的东西。正因为只读、无副作用，Resources 可以更宽松地暴露给模型，不需要像 Tools 那样谨慎授权。

最后是 **Prompts（提示模板）**，这个能力很多人容易忽略，但在团队协作场景下特别有用。Prompts 就是预定义的提示词模板，带参数占位符，解决的是「每次都要手写重复 prompt」的问题。举个例子，你的团队有一套固定的代码审查标准 prompt，接受「编程语言」和「代码内容」两个参数，调用时只需传入参数值，就能自动展开成完整的提示词，不用每次从头写。把公司积累的优质 prompt 封装成 MCP Prompts，所有人都能复用，统一标准，这在实际工程中很实用。

![Image](https://cdn.xiaolincoding.com//picgo/1776865817786-87eeb289-2779-4313-91d1-c3d3ff8d4c5a.png)

### 底层通信，JSON-RPC 2.0 是什么

理解 MCP 的底层，先要知道 JSON-RPC 是什么。

JSON-RPC 是一种轻量级的远程函数调用协议，用 JSON 格式来表达「调用」这件事。核心非常简单：客户端发一个 JSON 请求，里面说清楚「调哪个方法、参数是什么、这次请求的 ID 是多少」；服务端执行完，返回一个 JSON 响应，里面是执行结果或者错误信息。用 JSON 而不是二进制格式，好处是易读、易调试、语言无关，任何编程语言都能轻松实现。MCP 用的是它的 2.0 版本（JSON-RPC 2.0），相比 1.0 加了批量请求、通知消息等功能。

在传输层，MCP 支持两种方式。

第一种是 **stdio（标准输入输出）**，Server 作为本地子进程运行，Client 通过管道和它通信，Server 从 stdin 读消息，把结果写到 stdout。这种方式适合本地工具，不需要网络，启动快、延迟低，Claude Desktop 接本地 MCP Server 用的就是这种方式。

第二种是 **Streamable HTTP**，Server 作为 HTTP 服务部署在远程，Client 通过 HTTP 连接和它通信。这种方式适合远程部署的工具服务，或者需要多个 Client 共享同一个 Server 的场景，比如团队共用一个部署在服务器上的数据库 MCP Server，所有人的 AI 客户端都连同一个地址就行。

![Image](https://cdn.xiaolincoding.com//picgo/16d9e901ffaea2a01ab79931b0dc571c.png)

这里有个演进要说清楚：MCP 早期版本（2024-11-05 规范）用的是「HTTP + SSE」双端点方案，一个 GET 端点开 SSE 长连接接收推送，一个 POST 端点发请求，两个端点绑在一起工作。2025 年 3 月的规范更新里，这套方案被改成了 Streamable HTTP（老的 HTTP+SSE 被标记为 deprecated，但仍保留向后兼容）。

Streamable HTTP 并不是「抛弃 SSE」，而是把原来的两个端点合并成一个 `/mcp` 端点。Client 用 POST 发请求，Server 根据情况灵活返回：短请求直接回一个普通 JSON 响应，长请求则把这个 HTTP 响应升级为 SSE 流，持续推送中间结果。架构更简洁，部署也更友好（一个端点就够，serverless 环境也能跑），本质还是 HTTP 加 SSE，只是用法变了。

### MCP 生态发展这么快，背后的原因是什么

MCP 是 Anthropic 在 2024 年底发布的，发布后发展速度很快，主要有两个原因。

第一个原因是**极低的实现门槛**。Anthropic 开源了协议规范和多语言 SDK（Python、TypeScript 都有），写一个最简单的 MCP Server 不到 30 行代码，任何有基础编程经验的人都能上手。协议文档也写得清晰，社区很快就爆发出大量贡献。你想想，一个新技术如果上手成本很高，再好的设计也很难推广开，MCP 在这一点上做得很聪明。

第二个原因是**头部工具第一时间跟进**。GitHub、Slack、PostgreSQL、Puppeteer（浏览器自动化）、Google Maps 等高频工具都有了官方或社区维护的 MCP Server，开发者不需要自己写，直接用现成的就行。接一个新工具，在 Claude Desktop 的配置文件里加几行 JSON，重启后 Claude 自动发现并使用，整个过程零代码。当生态里可用的工具足够多，开发者就更愿意采用这套协议，形成了正向循环。

目前 Claude Desktop、Cursor、Windsurf 等主流 AI 工具都内置了 MCP 支持。对开发者来说，MCP 把「给 AI 接工具」这件事的门槛从「写一堆对接代码」降到了「改一行配置」，这才是它被快速采用的核心原因。

## 🎯 面试总结

回看开头的面试对话，最典型的误区就是把 MCP 和 Function Calling 搞混了。Function Calling 解决的是「模型怎么输出结构化的工具调用请求」，而 MCP 解决的是「工具怎么标准化接入、一次实现到处复用」，两者是不同层面的东西。另一个常见错误是以为 MCP 是 Anthropic 专属的，实际上它是开放协议，任何支持 MCP 的客户端都能接入。

面试回答这道题，首先要说清楚 MCP 解决的核心问题：工具接入碎片化，每接一个新工具都要单独写对接代码，换个客户端又得重写。

然后讲 Client-Server 架构，Server 是工具实现方，Client 是 AI 应用侧，一个 Client 可以连多个 Server。

重点要区分三类核心能力：Tools 是有副作用的操作（需要授权），Resources 是只读数据（无副作用），Prompts 是可复用的提示词模板。

底层通信用 JSON-RPC 2.0，传输层支持 stdio（本地）和 Streamable HTTP（远程）两种方式，早期的 HTTP+SSE 双端点方案在 2025 年 3 月的规范更新里被标记为 deprecated，推荐用单端点的 Streamable HTTP。

最后可以提一下 MCP 生态发展快的原因：实现门槛极低加上头部工具第一时间跟进。

对了，大模型面试题会在「**公众号@小林面试笔记题**」持续更新，林友们赶紧关注起来，别错过最新干货哦！

![Image](https://cdn.xiaolincoding.com//picgo/扫码_搜索联合传播样式-标准色版.png)
