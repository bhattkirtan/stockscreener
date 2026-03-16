# 🚀 START HERE for Lovable Integration

## Two Systems Available

This project has **2 independent systems**:

### 1. 📊 Strategy Optimization System (This Guide)
- Backtest and optimize trading strategies
- 20+ customizable parameters
- 12 instruments (Forex, Commodities, Crypto, Indices)
- **No live trading** - pure backtesting

### 2. 💹 Capital.com Trading Service (See Capital Service Docs)
- Live/demo trading with Capital.com API
- Position management (create, update, close)
- Account monitoring
- Webhook integration with TradingView
- Safety features & risk management

**This guide covers only the Optimization System (#1)**

---

## ✅ Step 1: Understand the Optimization API

Read: **[UI_CONTROL_API.md](./UI_CONTROL_API.md)**

**What you'll learn:**
- ✅ All 4 deployed optimization service URLs
- ✅ Complete API endpoints (Optimization + Scheduler + Data)
- ✅ 20+ optimization parameters explained
- ✅ 12 available instruments (Forex, Commodities, Crypto, Indices)
- ✅ Request/response examples
- ✅ Scheduler control (start/stop data sync from UI)

**Time: 5-10 minutes**

---

## ✅ Step 2: Copy the Code

Read: **[LOVABLE_INTEGRATION.md](./LOVABLE_INTEGRATION.md)**

**What you'll get:**
- ✅ Complete TypeScript types
- ✅ API service client
- ✅ Custom React hooks (useOptimizer)
- ✅ Ready-to-use components (Form, Results, History)
- ✅ shadcn/ui integration
- ✅ Working examples to copy-paste

**Time: 15-20 minutes to integrate**

---

## 🎯 That's It!

**Total time: 30 minutes** to fully integrate the optimization system into your Lovable project.

---

## 🔗 Optimization System URLs (Already Deployed)

All optimization services are **live and ready to use**:

| Service | URL | Purpose |
|---------|-----|---------|
| **Optimization API** | `https://optimize-api-6ovej2yaoa-uc.a.run.app` | Run strategy backtests |
| **Worker** | `https://optimizer-worker-6ovej2yaoa-uc.a.run.app` | Process optimization jobs |
| **Data Updater** | `https://data-updater-6ovej2yaoa-uc.a.run.app` | Update market data |
| **Scheduler Control** | `https://scheduler-control-6ovej2yaoa-uc.a.run.app` | Control data sync |

✅ **All CORS-enabled** for browser access  
✅ **All tested and healthy**  
✅ **No live trading** - backtesting only

---

## 🧪 Quick Test

Test the API is working:

```bash
# Health check
curl https://optimize-api-6ovej2yaoa-uc.a.run.app/health

# Scheduler status  
curl https://scheduler-control-6ovej2yaoa-uc.a.run.app/scheduler/status
```

---

## ⚠️ Ignore These Files

The docs folder has **16+ markdown files** with a lot of overlap. **You don't need most of them!**

**Ignore these:**
- ❌ API_CUSTOMIZATION_GUIDE.md (covered in UI_CONTROL_API.md)
- ❌ API_GUIDE.md (outdated)  
- ❌ API_README.md (outdated)
- ❌ FRONTEND_INTEGRATION.md (generic, use LOVABLE_INTEGRATION.md)
- ❌ UI_INTEGRATION_GUIDE.md (redundant)
- ❌ DEPLOYMENT*.md files (system already deployed)
- ❌ ARCHITECTURE files (not needed for integration)
- ❌ Old changelog/reorganization files

**Just read the 2 files above!** 👆

---

## 💡 Quick Integration Checklist

In your Lovable project:

1. [ ] Add environment variable: `VITE_OPTIMIZER_API_URL`
2. [ ] Create types from LOVABLE_INTEGRATION.md
3. [ ] Copy API service client code
4. [ ] Copy useOptimizer hook
5. [ ] Copy OptimizerForm component
6. [ ] Copy OptimizerResults component
7. [ ] Test in preview mode
8. [ ] Done! 🎉

---

## 🆘 Need Help?

1. **API not responding?** → Check URLs in [UI_CONTROL_API.md](./UI_CONTROL_API.md)
2. **CORS errors?** → All endpoints are CORS-enabled, check browser console
3. **Want more examples?** → See [LOVABLE_INTEGRATION.md](./LOVABLE_INTEGRATION.md)
4. **Deployment issues?** → All services already deployed and working

---

**Ready to build? Open [LOVABLE_INTEGRATION.md](./LOVABLE_INTEGRATION.md) and start coding! 🚀**

---

## 💹 Capital.com Trading Service (Separate System)

If you want to integrate **live trading** (not backtesting), the Capital.com service is also deployed:

**Capital Service URL**: Check the main Cloud Function deployment

**Features:**
- Create/update/close positions
- Account information
- Real-time position monitoring
- TradingView webhook integration
- Demo and Live mode support
- Safety features (max positions, trade limits)

**Documentation:**
- See `api-reference/` folder for Capital.com API docs
- See `getting-started/QUICKSTART.md` for Capital.com setup
- IMPORTANT: Review safety features before using live mode

**Note:** The optimization system (this guide) and Capital.com trading service are **completely separate** - you can use one without the other.

