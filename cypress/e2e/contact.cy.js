const homePage = require('../support/pages/homePage');

describe('Contact Links', () => {
  it('User accesses contact links', () => {
    homePage.visit();
    homePage.accessContactLinks();
  });
});