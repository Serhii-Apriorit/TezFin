import { getContract } from './toolkit';
import { AssetType } from './enum';
import bigInt from 'big-integer';

const alias = {
    [AssetType.OXTZ]: AssetType.XTZ,
    [AssetType.WTZ]: AssetType.XTZ,
    [AssetType.STXTZ]: AssetType.XTZ
}

export namespace PriceFeed {

    /**
     * Get the asset pair price from the TezFin oracle.
     * Uses the on-chain view `getPrice` which returns pair(timestamp, nat).
     */
    export async function GetPrice(
        asset: AssetType,
        oracle: string,
        level: number,
        server: string,
        priceOracle?: string,
    ): Promise<bigInt.BigInteger> {
        if (Object.prototype.hasOwnProperty.call(alias, asset)) {
            asset = alias[asset];
        }

        const contract = await getContract(server, oracle);

        // Previewnet fallback: on-chain views fail (tezlink_error), read directly from storage big_map
        if (server.includes('previewnet')) {
            const storage: any = await contract.storage();
            const entry = await storage.overrides.get(`${asset}-USD`);
            // entry is pair(timestamp, nat) — second element is the price
            return bigInt(entry['1'].toString());
        }

        // Try on-chain view; fall back if the node or underlying oracle rejects it (e.g. 500 / "Invalid view")
        try {
            const result = await contract.contractViews
                .getPrice(`${asset}-USD`)
                .executeView({ viewCaller: oracle });
            return bigInt(result['1'].toString());
        } catch {
            return GetPriceFallback(asset, contract, server, priceOracle);
        }
    }

    async function GetPriceFallback(
        asset: AssetType,
        tezFinOracleContract: any,
        server: string,
        priceOracle?: string,
    ): Promise<bigInt.BigInteger> {
        const storage: any = await tezFinOracleContract.storage();
        const pairKey = `${asset}-USD`;

        // 1. TezFinOracle overrides (e.g. USD-USD, USDT-USD)
        const overrideEntry = await storage.overrides.get(pairKey);
        if (overrideEntry !== undefined) {
            return bigInt(overrideEntry['1'].toString());
        }

        // 2. Resolve on-chain alias (e.g. TZBTC-USD → BTC-USD)
        let resolvedKey = pairKey;
        const aliasValue = await storage.alias.get(pairKey);
        if (aliasValue !== undefined) {
            resolvedKey = aliasValue;
        }

        // 3. Read from PriceOracle prices big_map: "XTZ-USD" → base "XTZ" → key "XTZUSDT"
        const base = resolvedKey.slice(0, resolvedKey.length - 4);
        if (!priceOracle) throw new Error(`Price not found for ${asset}: priceOracle not configured`);
        const priceOracleContract = await getContract(server, priceOracle);
        const priceOracleStorage: any = await priceOracleContract.storage();
        const priceEntry = await priceOracleStorage.prices.get(`${base}USDT`);
        if (priceEntry === undefined) {
            throw new Error(`Price not found for ${asset} (key: ${base}USDT)`);
        }
        return bigInt(priceEntry.price.toString());
    }
}
