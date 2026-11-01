// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// Test-only token for tests/test_simulation_anvil.py (runtime code in BatchToken.bin-runtime).
/// Rebuild: solc-0.8.28 --optimize --bin-runtime BatchToken.sol
/// claim() pays the caller 20 once; transfer() reverts on an insufficient balance.
contract BatchToken {
    mapping(address => uint256) public balanceOf;
    bool public claimed;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
    }

    function claim() external {
        require(!claimed, "already claimed");
        claimed = true;
        balanceOf[msg.sender] += 20;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        require(balanceOf[msg.sender] >= amount, "insufficient balance");
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
        return true;
    }
}
