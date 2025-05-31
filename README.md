# ⚡ MonadMesh – Decentralized Serverless Functions with Peer-to-Peer Parallel Execution

**MonadMesh** is a decentralized compute network that enables developers to submit pure functions (in WASM or Python), which are then executed across a peer-to-peer (P2P) network of nodes - powered by [Monad](https://monad.xyz)'s blazing-fast parallel blockchain.

> 💡 Think Cloudflare Workers meets IPFS meets Monad’s superpowers.

---

## 🌐 Live Demo

> Coming soon… [Link to deployment or demo video]

---

## 📌 Features

### 🧠 Smart Function Submission
- WASM/Python function input with syntax highlighting
- Monaco-powered in-browser code editor with execution previews
- MetaMask/Coinbase wallet integration (via Monad RPC)

### 📊 Real-Time Task Dashboard
- Live task lifecycle updates via WebSockets
- Tracks job status, node assignment, and execution logs in real-time
- Individual task cards with progress indicators

### 🖼️ Result Visualization
- JSON viewer for structured outputs
- D3.js graphs to visualize numerical/computational results
- User-friendly mode toggle: Table / JSON / Graph

### 🗺️ Peer-to-Peer Node Map
- Real-time interactive node map
- Visualizes active compute participants and their geolocations (approximate)

### 🛡️ ZK-Proof Toggle *(Experimental)*
- Toggle zero-knowledge proof generation
- Uses zkSNARKs for correctness verification of compute tasks

---

## 🧰 Tech Stack

| Layer           | Technology                                |
|----------------|--------------------------------------------|
| Frontend       | Next.js 14 (App Router), React, TypeScript |
| Blockchain     | Monad RPC (EVM-compatible), Web3.js        |
| Code Editor    | Monaco Editor                              |
| Live Updates   | WebSockets                                 |
| Data Viz       | D3.js                                      |
| Backend        | Python-based Task Orchestrator             |

---

## 🧪 How It Works

### 🔁 Workflow

1. 📝 **Submit Function**:  
   User writes a pure function in Python/WASM via the frontend submission panel.

2. 🧠 **Task Orchestration**:  
   A Python orchestrator handles routing to P2P nodes and initiates compute requests.

3. 🔗 **On-Chain Tracking**:  
   Monad smart contracts log the compute task hashes and handle execution verification.

4. ⚙️ **Parallel Execution**:  
   Nodes compute the task in parallel; results are submitted and verified on-chain.

5. 📊 **Frontend Display**:  
   Live results appear via WebSocket updates; visualized through graphs or structured data views.

---

## 🧱 Architecture Diagram

![MonadMesh Architecture](https://github.com/S-YED/MonadMesh/blob/main/assets/architecture%20diagram.jpg)

*(You can replace this with a real diagram or link)*

---

## 🚀 Upscaling & Roadmap

- **ZK-Proofs for Result Verification** – Full zkSNARK integration.
- **Monad-Specific L1 Optimizations** – Further leverage Monad’s parallelism.
- **IPFS Integration** – For handling large datasets and input payloads.
- **Persistent State Storage** – Integrating off-chain storage or L2 solutions.
- **Improved Developer UX** – Better templates, task previews, and testnet faucet integration.

---

## 🛠️ Setup & Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/monadmesh.git
cd monadmesh

# Install dependencies
npm install

# Run the development server
npm run dev
``` 

## 🤝 Contributing

Feel free to fork the repo, open issues, or suggest new features. We welcome contributors!

```bash
# Create a new branch
git checkout -b feature/your-feature-name

# Push and open a PR
git push origin feature/your-feature-name
```

## 👥 Collaborators

This project was built with ♥ by:

- **Your Name** – [@s-yed](https://github.com/s-yed)  
- **Collaborator 1** – [@drraghavendra](https://github.com/drraghavendra)  
- **Collaborator 2** – [@scienmanas](https://github.com/scienmanas)

We built MonadMesh during the [Monad Blitz Bangalore 2025](https://lu.ma/0k7yvinp?tk=8SHdBN) hackathon, and are continuing to evolve it for open-source and production deployment.

## 📄 License

MIT License. See [LICENSE](./LICENSE) for more details.

## 💬 Connect With Us

Have feedback or want to collaborate?  
- Twitter: [@yourhandle](https://twitter.com/SKM_Ahmed1)  
- Discord: [Join our dev chat](https://discord.gg/ahmed_indian)  
- Email: syedkhajamoinuddin293@gmail.com
